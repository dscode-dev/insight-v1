"""O ajuste e a aplicacao do normalizador — exatos, puros e versionados.

    NormalizerFitArtifact = Fit(FeaturePopulation, Competition, Cutoff)
    Normalized(x)         = (x - mediana) / IQR

O QUE MORA AQUI: a populacao com digest, o artefato imutavel, o ajustador puro
e o transformador.

O QUE NAO MORA: qual populacao historica usar, qual grade de cortes, qual
divisao de treino e avaliacao. Sem essas decisoes «ajustar o normalizador» nao
tem populacao cientificamente definida — e elas pertencem ao PR-05.5.
"""
