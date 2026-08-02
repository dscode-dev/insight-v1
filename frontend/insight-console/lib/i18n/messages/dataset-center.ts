// Dataset Center (data-intelligence/datasets) translations. Operational +
// data-intelligence terminology kept consistent with the rest of the Console.
import type { Locale } from "../config";

export const datasetCenter: Record<Locale, Record<string, string>> = {
  en: {
    title: "Dataset Center",
    subtitle:
      "Immutable Atlas datasets, records, intelligence categories, checksums and lineage.",
    // ingestion metrics
    "ing.signals": "Signals",
    "ing.behaviors": "Behaviors",
    "ing.vectors": "Vectors",
    "ing.memories": "Memories",
    "ing.batches": "Ingestion batches",
    // filters + list
    filtersTitle: "Dataset filters",
    allCategories: "All categories",
    registeredDatasets: "Registered datasets ({count})",
    noDatasets: "No registered datasets match this filter.",
    rowsCategory: "{count} rows · {category}",
    // records
    recordsTitle: "Records — {name}",
    recFormat: "Format",
    recValid: "Valid",
    recInvalid: "Invalid",
    recRegisteredBy: "Registered by",
    rowLabel: "Row",
    // import
    importTitleSuper: "Atlas Dataset Import — SuperAdmin",
    importTitle: "Atlas Dataset Import",
    importHelp:
      "Accepted: CSV, JSON, NDJSON and Parquet, up to 25 MB. Categories: fixtures, statistics, odds, behaviors, memory and signals. Validation never registers data; Register Dataset persists the original, canonical NDJSON, checksum, lineage and manifest.",
    superRequired:
      "Dataset validation and registration require the Gateway-authenticated SuperAdmin role.",
    validateBtn: "Validate Dataset",
    registerBtn: "Register Dataset",
    // validation result
    valStatus: "Status",
    valRows: "Rows",
    valValid: "Valid",
    valInvalid: "Invalid",
    valChecksum: "Checksum",
    validationDetails: "Validation details and preview",
    // errors
    errUnavailable: "Dataset Center unavailable.",
    errValidation: "Validation failed.",
    errRegistration: "Registration failed.",
    errSelectFile: "Select a file first.",
  },
  "pt-BR": {
    title: "Centro de Datasets",
    subtitle:
      "Datasets imutáveis do Atlas, registros, categorias de inteligência, checksums e linhagem.",
    "ing.signals": "Sinais",
    "ing.behaviors": "Comportamentos",
    "ing.vectors": "Vetores",
    "ing.memories": "Memórias",
    "ing.batches": "Lotes de ingestão",
    filtersTitle: "Filtros de dataset",
    allCategories: "Todas as categorias",
    registeredDatasets: "Datasets registrados ({count})",
    noDatasets: "Nenhum dataset registrado corresponde a este filtro.",
    rowsCategory: "{count} linhas · {category}",
    recordsTitle: "Registros — {name}",
    recFormat: "Formato",
    recValid: "Válidas",
    recInvalid: "Inválidas",
    recRegisteredBy: "Registrado por",
    rowLabel: "Linha",
    importTitleSuper: "Importação de Dataset do Atlas — SuperAdmin",
    importTitle: "Importação de Dataset do Atlas",
    importHelp:
      "Aceitos: CSV, JSON, NDJSON e Parquet, até 25 MB. Categorias: fixtures, statistics, odds, behaviors, memory e signals. A validação nunca registra dados; Registrar Dataset persiste o NDJSON original e canônico, checksum, linhagem e manifesto.",
    superRequired:
      "A validação e o registro de datasets exigem o papel SuperAdmin autenticado pelo Gateway.",
    validateBtn: "Validar dataset",
    registerBtn: "Registrar dataset",
    valStatus: "Status",
    valRows: "Linhas",
    valValid: "Válidas",
    valInvalid: "Inválidas",
    valChecksum: "Checksum",
    validationDetails: "Detalhes e prévia da validação",
    errUnavailable: "Centro de Datasets indisponível.",
    errValidation: "Falha na validação.",
    errRegistration: "Falha no registro.",
    errSelectFile: "Selecione um arquivo primeiro.",
  },
};
