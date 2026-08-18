"""A publicação do corpus histórico: composição, materialização, manifesto.

    domain/corpus     O QUE um corpus é — versão, pertinência, manifesto
    historical/corpus COMO uma versão é composta e publicada

A separação é a mesma de `domain/build` e `historical/build`, e pela mesma
razão: o domínio precisa ser testável sem banco, sem object store e sem
pyarrow, e um único pacote arrastaria as três dependências para dentro dele.
"""
