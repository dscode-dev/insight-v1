"""A leitura do dataset cru e a escrita do normalizado, em Parquet.

    reader.py        lê `MATCH_STATE_RAW_V2` em lotes, projetado e podado
    materializer.py  escreve a representação normalizada

OS DOIS FICAM AQUI, e não em `historical/features/`, porque o pacote de lá tem
uma responsabilidade fechada — materializar o dataset CRU — e acrescentar a
leitura dele a esse mesmo módulo faria o materializador do PR-05.5.1 crescer
para servir a um consumidor que ele não conhece.
"""
