let
    Fonte = Csv.Document(
        File.Contents("C:\\CAMINHO\\base_estoque.csv"),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]
    ),
    Cabecalhos = Table.PromoteHeaders(Fonte, [PromoteAllScalars = true]),
    Tipos = Table.TransformColumnTypes(Cabecalhos, {
        {"DataReferencia", type date},
        {"Hospital", type text},
        {"CodigoMaterial", type text},
        {"Material", type text},
        {"Categoria", type text},
        {"Lote", type text},
        {"Validade", type date},
        {"EstoqueAtual", Int64.Type},
        {"EstoqueMinimo", Int64.Type},
        {"Consumo30Dias", Int64.Type},
        {"ValorUnitario", Currency.Type}
    }),
    ColunaValorEstoque = Table.AddColumn(
        Tipos,
        "ValorEstoque",
        each [EstoqueAtual] * [ValorUnitario],
        Currency.Type
    ),
    ColunaDiasAteVencimento = Table.AddColumn(
        ColunaValorEstoque,
        "DiasAteVencimento",
        each Duration.Days([Validade] - [DataReferencia]),
        Int64.Type
    )
in
    ColunaDiasAteVencimento
