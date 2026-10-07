# Kit para montar o Estoque em Foco no Power BI Desktop

Este pacote ainda não é um arquivo `.pbix` nem um projeto `.pbip`. Ele reúne a base de demonstração e as definições para montar o relatório no Power BI Desktop.

## Abrir e montar

1. Extraia o ZIP para uma pasta no seu computador.
2. Abra o Power BI Desktop.
3. Selecione **Obter dados > Texto/CSV** e escolha `data/base_estoque.csv`.
4. No Power Query, confira os tipos das colunas conforme `powerbi/Modelo-e-visuais.md`. A consulta de referência está em `powerbi/Power-Query.m`; como alternativa, importe o CSV pela interface.
5. No modelo, renomeie a tabela para `FatoEstoque`.
6. Crie as medidas e a coluna calculada listadas em `powerbi/Medidas-DAX.md`.
7. Monte os cartões, filtros, gráfico e tabela seguindo `powerbi/Modelo-e-visuais.md`.
8. Salve no Desktop em **Arquivo > Salvar como** e escolha `.pbix`.

## Sobre os dados

A base contém registros sintéticos para demonstração. Não representa dados reais de hospitais, pacientes ou operações. Valide regras e dados antes de qualquer uso operacional.
