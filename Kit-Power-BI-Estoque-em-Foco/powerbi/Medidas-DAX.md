# Medidas DAX

Crie as medidas abaixo na tabela `FatoEstoque`. A base tem um retrato mensal por hospital, material e lote. Para os cartões de posição atual, a medida encontra a última data disponível respeitando o hospital selecionado.

```DAX
Última Data =
CALCULATE(
    MAX(FatoEstoque[DataReferencia]),
    REMOVEFILTERS(FatoEstoque[DataReferencia])
)

Valor em Estoque =
VAR DataAtual = [Última Data]
RETURN
    CALCULATE(
        SUMX(FatoEstoque, FatoEstoque[EstoqueAtual] * FatoEstoque[ValorUnitario]),
        FatoEstoque[DataReferencia] = DataAtual
    )

Itens Abaixo do Mínimo =
VAR DataAtual = [Última Data]
RETURN
    CALCULATE(
        COUNTROWS(FILTER(FatoEstoque, FatoEstoque[EstoqueAtual] < FatoEstoque[EstoqueMinimo])),
        FatoEstoque[DataReferencia] = DataAtual
    )

Itens Monitorados =
VAR DataAtual = [Última Data]
RETURN
    CALCULATE(DISTINCTCOUNT(FatoEstoque[CodigoMaterial]), FatoEstoque[DataReferencia] = DataAtual)

% Itens Abaixo do Mínimo =
DIVIDE([Itens Abaixo do Mínimo], [Itens Monitorados], 0)

Lotes a Vencer em 30 Dias =
VAR DataAtual = [Última Data]
RETURN
    CALCULATE(
        COUNTROWS(FILTER(FatoEstoque, FatoEstoque[Validade] >= DataAtual && FatoEstoque[Validade] <= DataAtual + 30)),
        FatoEstoque[DataReferencia] = DataAtual
    )

Cobertura Média (dias) =
VAR DataAtual = [Última Data]
VAR Unidades = CALCULATE(SUM(FatoEstoque[EstoqueAtual]), FatoEstoque[DataReferencia] = DataAtual)
VAR Consumo = CALCULATE(SUM(FatoEstoque[Consumo30Dias]), FatoEstoque[DataReferencia] = DataAtual)
RETURN DIVIDE(Unidades * 30, Consumo, 0)

Valor em Estoque (Histórico) =
SUMX(FatoEstoque, FatoEstoque[EstoqueAtual] * FatoEstoque[ValorUnitario])

Status do Estoque =
IF(FatoEstoque[EstoqueAtual] < FatoEstoque[EstoqueMinimo], "Repor", "Regular")
```

> `Status do Estoque` é uma coluna calculada, não uma medida. Crie-a em **Nova coluna**.

## Formatação sugerida

- `Valor em Estoque` e `Valor em Estoque (Histórico)`: moeda BRL, sem casas decimais.
- `% Itens Abaixo do Mínimo`: percentual, uma casa decimal.
- `Cobertura Média (dias)`: número inteiro com sufixo “dias” no título do cartão.
