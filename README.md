# Estoque em Foco — Portfólio Power BI

Demonstração de um painel de gestão de estoque hospitalar, com indicadores de cobertura, risco de ruptura, lotes próximos ao vencimento e valor imobilizado.

**Os registros são sintéticos.** Não representam dados de pacientes, hospitais ou resultados de clientes.

## Acessar

- [Abrir a réplica visual na nuvem](https://eliasnrodrigues.github.io/dropxl-ebay-espanha/)
- [Abrir catálogo de produtos para anúncios manuais no eBay Espanha](https://eliasnrodrigues.github.io/dropxl-ebay-espanha/catalogo-ebay-espanha/)
- [Ver o repositório](https://github.com/eliasnrodrigues/dropxl-ebay-espanha)

## Entrega Power BI e versão online

Em projetos contratados, o dashboard é desenvolvido e entregue como arquivo **Power BI Desktop (.pbix)**. A página deste portfólio é uma **replicação na nuvem do template Power BI**, para demonstrar o visual e a navegação. Ela não substitui o arquivo Power BI nem equivale à publicação do relatório no Power BI Service.

Este repositório contém a réplica web, uma base sintética e materiais de referência para reproduzir o relatório no Power BI Desktop; não contém um arquivo .pbix.

## O que a demonstração apresenta

- Série histórica por unidade, material e lote.
- Valor em estoque, itens abaixo do mínimo, vencimentos próximos e cobertura estimada.
- Filtros por hospital e período, tendência mensal, composição por categoria e lista de prioridade.
- Referências de Power Query, DAX e construção dos visuais.

## Reproduzir no Power BI Desktop

1. Baixe data/base_estoque.csv.
2. No Power BI Desktop, escolha **Obter dados → Texto/CSV** e carregue a base.
3. Nomeie a tabela como FatoEstoque. Use powerbi/Power-Query.m como referência para os tipos e tratamento.
4. Crie as medidas descritas em powerbi/Medidas-DAX.md.
5. Monte as páginas com os visuais indicados em powerbi/Modelo-e-visuais.md.

## Estrutura

- index.html, assets/: réplica visual interativa na nuvem.
- data/base_estoque.csv: base sintética para a página e o Power BI.
- powerbi/: consulta M, medidas DAX e documentação do modelo.
- .github/workflows/pages.yml: publicação no GitHub Pages.

Cada atualização da branch main publica a réplica online pelo GitHub Actions.
