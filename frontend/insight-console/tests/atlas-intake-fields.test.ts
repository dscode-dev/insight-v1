// O formulário monta o JSON que o Atlas vai julgar.
//
// O que estes testes protegem é uma coisa só: que a tela NUNCA mande um
// documento que ela própria sabe estar em desacordo consigo mesmo. O Atlas
// recusa esses casos e nomeia o campo, então nada se perde — mas uma recusa
// que a tela poderia ter evitado é uma ida e volta que o operador paga.

import { describe, expect, it } from "vitest";

import {
  BLOCOS_DO_CONTRATO,
  campoPertenceAoPerfil,
  lerPerfil,
  montarRegistro,
  valoresDeExemplo,
} from "@/lib/atlas-intake-fields";

const SCHEMA = "atlas.match.v1";

function registro(valores: Record<string, string>) {
  return montarRegistro(valores, SCHEMA) as Record<string, any>;
}

describe("perfil declarado", () => {
  it("o exemplo declara os quatro blocos e traz os quatro", () => {
    const saida = registro(valoresDeExemplo());
    expect(saida.provenance.profile).toEqual([...BLOCOS_DO_CONTRATO]);
    expect(saida.market.opening).toBeDefined();
    expect(saida.market.closing).toBeDefined();
    expect(saida.stats).toBeDefined();
  });

  it("core entra mesmo sem ninguém marcar", () => {
    // Deixar desmarcar produziria só uma recusa evitável: sem núcleo a
    // contribuição não sabe de que partida está falando.
    expect(lerPerfil({ "provenance.profile": "" })).toContain("core");
    expect(lerPerfil({})).toEqual(["core"]);
  });

  it("mantém a ordem do contrato, não a ordem em que foi clicado", () => {
    expect(lerPerfil({ "provenance.profile": "stats,market_open,core" })).toEqual([
      "core",
      "market_open",
      "stats",
    ]);
  });

  it("ignora bloco repetido", () => {
    expect(lerPerfil({ "provenance.profile": "core,stats,stats" })).toEqual([
      "core",
      "stats",
    ]);
  });
});

describe("o que é enviado segue o que foi declarado", () => {
  it("bloco desmarcado não vai vazio — some do documento", () => {
    // Mandá-lo vazio seria "trouxe sem declarar", que o Atlas recusa; e
    // mandá-lo com strings vazias seria pior ainda, porque pareceria um
    // preenchimento.
    const valores = { ...valoresDeExemplo(), "provenance.profile": "core,market_close" };
    const saida = registro(valores);

    expect(saida.provenance.profile).toEqual(["core", "market_close"]);
    expect(saida.stats).toBeUndefined();
    expect(saida.market.opening).toBeUndefined();
    expect(saida.market.closing).toBeDefined();
  });

  it("o núcleo vai sempre, marque-se o que se marcar", () => {
    const valores = { ...valoresDeExemplo(), "provenance.profile": "core" };
    const saida = registro(valores);

    expect(saida.identity.competition).toBe("premier_league");
    expect(saida.result.home_goals).toBe(2);
    expect(saida.provenance.source).toBe("football_data");
    expect(saida.market).toBeUndefined();
  });

  it("a casa de aposta acompanha qualquer metade do mercado", () => {
    // Uma fonte que traga só a abertura ainda precisa dizer de quem ela é.
    for (const metade of ["market_open", "market_close"]) {
      const saida = registro({
        ...valoresDeExemplo(),
        "provenance.profile": `core,${metade}`,
      });
      expect(saida.market.bookmaker).toBe("bet365");
    }
  });

  it("o fuso é enviado e não tem padrão", () => {
    const saida = registro(valoresDeExemplo());
    expect(saida.provenance.timezone).toBe("Europe/London");

    // Em branco vai como vazio, e não omitido: a recusa fala do valor, que é
    // onde a pessoa está olhando.
    const vazio = registro({ ...valoresDeExemplo(), "provenance.timezone": "" });
    expect(vazio.provenance.timezone).toBe("");
  });
});

describe("quais campos a tela mostra", () => {
  it("esconde exatamente os campos do bloco desmarcado", () => {
    const perfil = ["core", "stats"];
    expect(campoPertenceAoPerfil("stats.home.shots", perfil)).toBe(true);
    expect(campoPertenceAoPerfil("market.closing.home", perfil)).toBe(false);
    expect(campoPertenceAoPerfil("market.opening.home", perfil)).toBe(false);
    expect(campoPertenceAoPerfil("market.bookmaker", perfil)).toBe(false);
  });

  it("o núcleo nunca é escondido", () => {
    for (const caminho of [
      "identity.competition",
      "result.home_goals",
      "provenance.source",
      "provenance.timezone",
    ]) {
      expect(campoPertenceAoPerfil(caminho, ["core"])).toBe(true);
    }
  });
});
