# dropXL + eBay Europa

Integração em Python para anunciar produtos aprovados, atualizar preço/estoque, encaminhar pedidos pagos à dropXL e devolver rastreamento ao eBay. Inclui execução em servidor Docker com estado persistente e demonstração sem credenciais.

**Estado da entrega:** código e testes locais prontos; contas, credenciais, catálogo real e publicação ainda não configurados. Não houve vendas, compras de fornecedor nem implantação em hospedagem. A validação com APIs reais depende das suas contas sandbox.

## Experimente agora

Na pasta `dropxl-ebay-europa`, com Python 3.12+:

```bash
python bridge.py demo
python -m unittest discover -s tests -v
```

A demonstração usa dados de teste: pedido pago → envio ao fornecedor → etapa de pagamento manual simulada → rastreamento. Não chama APIs. Os testes verificam duplicidade, resposta perdida, cancelamento, destino, margem, estoque e rastreamento.

## Como o negócio funciona

O comprador paga no eBay. Você compra do fornecedor, que entrega ao cliente. Sua receita é a diferença após custos; esse modelo é dropshipping, e exige operação como vendedor.

A documentação pública da dropXL informa que pedidos criados por API ficam em **Unsubmitted orders** e precisam de pagamento manual; não oferece pagamento de pedidos por essa API. O trabalhador cria o pedido e registra `submitted_unpaid`, para você pagar no painel. Confirme com a dropXL se sua conta possui outro acordo de pagamento. A conta é habilitada por país e a API limita chamadas a uma por segundo; o conector aplica esse intervalo.

O eBay permite fornecedores atacadistas, mantendo o vendedor responsável pela entrega e satisfação do comprador. Atendimento, devoluções, cancelamentos e questões fiscais precisam ser resolvidos na operação. A admissão da sua conta como vendedor e na dropXL precisa ser confirmada antes de contratar hospedagem ou anunciar.

## Configuração inicial

1. Escolha **um país**: ES, DE, FR, IT ou NL. A integração usa EUR e o idioma do marketplace escolhido. Espanha em `.env.example` é apenas exemplo. Não cobre toda a Europa com uma conta de país único.
2. Cadastre/habilite sua conta dropXL para esse país e solicite acesso API e sandbox ao suporte. As credenciais usam e-mail e token da API.
3. Habilite conta de vendedor eBay e conta no [eBay Developers Program](https://developer.ebay.com/). Gere credenciais sandbox primeiro. Obtenha um **refresh token de usuário** com `sell.inventory` e `sell.fulfillment` pelo fluxo de consentimento eBay; o código renova o access token automaticamente.
4. No eBay, habilite business policies e crie políticas de pagamento, entrega e devolução. Informe os três IDs e a localização de estoque (`EBAY_LOCATION_KEY`). A localização deve representar o fornecedor/centro de expedição real. Essa etapa não é criada automaticamente.
5. Copie `.env.example` para `.env` **no servidor** e preencha os campos. Mantenha as credenciais fora do GitHub; não envie senha ou token pelo chat. Sandbox e produção têm credenciais diferentes.
6. Obtenha o feed autorizado de produtos dropXL para o país/idioma. Use `examples/catalog.example.json` como modelo para preencher `catalog.json`. Os campos de categoria eBay, imagens, descrição, EAN e características exigidas precisam ser revisados. `approved: true` inclui o produto na sincronização; a lista começa vazia.
7. Informe dados de fabricante/segurança exigidos no campo `regulatory` conforme o esquema eBay aplicável à categoria. O conector não inventa esses dados nem mapeia categorias automaticamente. Enriquecimento/importação automática do feed CSV não está incluído nesta versão.
8. Configure `carriers.json` com o ID da transportadora dropXL e o código aceito pelo eBay para sua conta. Exemplo estrutural: `{"8":"DPD"}`. Confirme o mapeamento antes de usar; o arquivo inicial está vazio.

### Preço

Preencha suas taxas reais em `.env`: `ESTIMATED_FEE_RATE`, `TARGET_MARGIN_RATE`, `FIXED_COST_EUR`, `RESERVE_EUR`. Taxas são frações: `0.15` significa 15%, apenas exemplo. Não são estimativas oficiais de eBay.

`landed_cost_factor` por produto converte o preço retornado pelo fornecedor em custo total adotado por você (ex.: encargos não incluídos); `shipping_cost_eur` adiciona frete por unidade. Confirme se o preço da sua conta inclui impostos e frete para evitar omissão ou cobrança dupla. A fórmula é:

`preço = (custo total + custo fixo + reserva) / (1 − taxa estimada − margem desejada)`

O valor arredonda para cima em centavos. Antes de criar pedido no fornecedor, o conector verifica estoque e compara o valor pago com o mínimo calculado. Essa proteção depende dos custos corretamente configurados; não é uma apuração de lucro contábil.

## Rodar na nuvem

Use um servidor Linux com Docker e Compose, disco persistente e conexão de saída HTTPS. **GitHub guarda o código; GitHub Pages não executa este backend.** A hospedagem não foi contratada nem implantada nesta entrega. O Dockerfile/Compose permitem implantação no provedor que você escolher; o processo não exige porta pública.

Baixe esta branch do repositório, entre na pasta `dropxl-ebay-europa`, configure `.env`, `catalog.json`, `carriers.json` e execute:

```bash
docker compose build
docker compose run --rm bridge python bridge.py check
docker compose run --rm bridge python bridge.py catalog
docker compose run --rm bridge python bridge.py orders
```

Com `ENABLE_WRITES=false`, o catálogo mostra planos e os pedidos não são enviados. Para testar a escrita **no sandbox**, configure `ENABLE_WRITES=true`; `PUBLISH_LISTINGS=false` cria ofertas sem publicá-las. Após validar categorias, políticas e imagens, `PUBLISH_LISTINGS=true` permite publicar. A habilitação de escrita também permite criar pedidos no fornecedor.

Para produção, use novas credenciais e **um volume de estado separado**; ajuste `API_ENVIRONMENT=production`, `ENABLE_WRITES=true`, e `PRODUCTION_ACK=I_CONFIGURED_MY_SELLER_ACCOUNT`. Publique apenas após validar a operação. A confirmação é uma configuração técnica, não contratação de serviço.

```bash
docker compose up -d
docker compose logs --tail=50 bridge
docker compose exec bridge python bridge.py status
docker compose stop
```

O ciclo padrão roda a cada 15 minutos. O volume `bridge-state` mantém as referências entre reinícios; faça backup. Não use `docker compose down -v` na operação, pois apagaria esse estado. Apenas um worker pode operar esse banco; a trava de arquivo impede duas instâncias simultâneas. Use volumes separados para contas/países/ambientes distintos. O backend direto de produção usa trava Linux; demonstração e testes também funcionam localmente sem Docker.

## Rotina e limites

- Pague os novos pedidos na dropXL e acompanhe a expedição. `status` mostra IDs e pendências; não guarda endereços de clientes no banco nem logs.
- `manual_review`: trate cancelamentos, estornos, diferenças de margem/endereço, transportadora ou múltiplos volumes no painel. O conector não cancela nem reembolsa automaticamente.
- `unknown`: a criação pode ter sido aceita com a resposta perdida. A busca por `EBAY-<orderId>` reconcilia nas próximas execuções; nunca recria automaticamente após esse estado. Se a referência não aparecer, verifique com o fornecedor antes de editar o banco.
- Rastreamento automático atende **uma unidade em uma linha de pedido e um volume**. Mais linhas, múltiplos volumes ou rastreamento ambíguo ficam para revisão; evita marcar todo o pedido como enviado indevidamente.
- Pedidos são consultados com paginação e modificações nos últimos 30 dias. Após parada maior que esse período, confira pedidos antigos manualmente. Pedidos já enviados ao fornecedor continuam sendo acompanhados pelo banco.
- Estoque usa reserva de segurança e limite por anúncio; não elimina mudanças entre consulta e compra. Produto que desaparece do fornecedor recebe estoque zero no eBay. Se você remover um produto do `catalog.json` ou desmarcar `approved`, encerre/zere o anúncio no eBay também; retirada automática do catálogo ainda não foi implementada.
- Se uma oferta já registrada desaparecer, a recriação exige revisão. Falhas parciais do eBay interrompem o ciclo e precisam de inspeção no painel. Reinícios mantêm as referências.
- Não há painel web nesta versão. Operação por CLI, logs e painéis eBay/dropXL. O CI do GitHub roda testes e demonstração; não executa vendas nem armazena dados comerciais.

## Fontes oficiais verificadas em 10/10/2026

- [dropXL: API](https://b2b.dropxl.com/pages/1-api)
- [dropXL: formas de sincronização e feed](https://www.dropxl.com/synchronisation-method-page.html)
- [eBay: dropshipping](https://www.ebay.com/help/selling/listings/creating-managing-listings/drop-shipping?id=4176)
- [eBay: campos de publicação](https://developer.ebay.com/api-docs/sell/static/inventory/publishing-offers.html)
- [eBay: autorização](https://developer.ebay.com/develop/guides/sell/authorization)
- [eBay: gestão de anúncios](https://developer.ebay.com/develop/guides/sell/listing-management)

Não foram usados tokens reais. Execute o ensaio com sua conta sandbox antes de considerar a integração pronta para produção.
