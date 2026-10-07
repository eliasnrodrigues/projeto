# Modelo e construção dos visuais

## Tabela de fatos

`FatoEstoque` contém um registro por mês, hospital, material e lote. A granularidade permite analisar a posição mensal e consultar lote/validade.

| Campo | Tipo | Uso |
|---|---|---|
| DataReferencia | Data | Eixo temporal e última posição |
| Hospital | Texto | Segmentação de unidade |
| CodigoMaterial | Texto | Identificador do material |
| Material | Texto | Nome exibido |
| Categoria | Texto | Agrupamento de estoque |
| Lote | Texto | Rastreio demonstrativo |
| Validade | Data | Monitoramento de vencimento |
| EstoqueAtual | Inteiro | Saldo em unidades |
| EstoqueMinimo | Inteiro | Limite de reposição |
| Consumo30Dias | Inteiro | Consumo estimado mensal |
| ValorUnitario | Moeda | Cálculo de valor estocado |

## Página 1 — Visão geral

1. Segmentadores: `Hospital` e `DataReferencia`.
2. Cartões: `Valor em Estoque`, `Itens Abaixo do Mínimo`, `Lotes a Vencer em 30 Dias`, `Cobertura Média (dias)`.
3. Linha: `DataReferencia` no eixo e `Valor em Estoque (Histórico)` nos valores.
4. Rosca: `Categoria` na legenda e `Valor em Estoque` nos valores.
5. Tabela de prioridade: `Material`, `Hospital`, `EstoqueAtual`, `EstoqueMinimo`, `Validade`, `Status do Estoque`; filtrar para itens abaixo do mínimo ou vencendo em até 30 dias.

## Cuidados de interpretação

- A base é sintética e serve para demonstrar modelagem, indicadores e narrativa visual.
- Cobertura é estimada por `EstoqueAtual / Consumo30Dias × 30`; não considera sazonalidade futura ou pedidos em trânsito.
- Para uso operacional, substitua os dados por uma fonte autorizada e valide regras de lote, unidade de medida, consumo e validade com a área responsável.
