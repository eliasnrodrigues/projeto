# Estoque em Foco — Portfólio Power BI

Dashboard demonstrativo de gestão de estoque hospitalar, com foco em cobertura, risco de ruptura, lotes próximos ao vencimento e valor imobilizado.

**Projeto demonstrativo:** todos os registros da base são sintéticos. Não representam dados de pacientes, hospitais ou da experiência profissional de qualquer instituição.

## Acessar

- [Abrir o dashboard online](https://eliasnrodrigues.github.io/projeto/)
- [Ver o repositório](https://github.com/eliasnrodrigues/projeto)

## O que o projeto demonstra

- Modelagem de dados em série histórica por unidade, material e lote.
- Indicadores de valor em estoque, itens abaixo do mínimo, vencimentos próximos e cobertura estimada.
- Filtros por hospital e janela temporal, tendência mensal, composição por categoria e tabela de prioridade.
- Preparação de dados em Power Query e medidas em DAX para reprodução no Power BI Desktop.

## Reproduzir no Power BI Desktop

1. Baixe `data/base_estoque.csv`.
2. No Power BI Desktop, escolha **Obter dados → Texto/CSV** e carregue a base.
3. Nomeie a tabela como `FatoEstoque`. Use `powerbi/Power-Query.m` como referência para os tipos e tratamento de colunas.
4. Crie as medidas descritas em `powerbi/Medidas-DAX.md`.
5. Monte as páginas com os visuais e campos indicados em `powerbi/Modelo-e-visuais.md`.

## Estrutura

- `index.html`, `assets/`: versão web interativa para visualização do portfólio.
- `data/base_estoque.csv`: base de demonstração para Power BI.
- `data/base_estoque.csv`: base usada tanto pela página online como pelo Power BI.
- `powerbi/`: consulta M, medidas DAX e documentação do modelo.
- `.github/workflows/pages.yml`: publicação automática no GitHub Pages.

## Atualizar publicação

Cada envio para a branch `main` dispara a publicação pelo GitHub Actions. A página fica disponível em `https://eliasnrodrigues.github.io/projeto/` quando o Pages concluir a primeira implantação.
