# AZTECA-INSIGHTS-A — Smoke Checklist (authenticated, app build)

Backend-free sprint: smoke is client-side against the existing real contract.

1. Open **Profile ▸ Estatísticas**.
2. ✅ Values shown: **Publicações, Sinais, Seguidores, Seguindo** (tiles) + **Reputação, Comunidades** (rows).
3. ✅ **"precisão" is GONE** (it was stub-backed fabrication). Confirm no percentage-accuracy metric appears.
4. ✅ Numbers match the API: `curl -H "Authorization: Bearer $TOK" $B/v1/users/$MY_ID/sports-profile | jq .stats`
   → the tile values equal `posts/signals/followers/following`, rows equal `reputation`/`communities`.
5. ✅ **No sparkline / no trend line / no delta arrow** anywhere in Statistics (there is no baseline or series
   in the contract — arrows would be fabrication).
6. ✅ **No freshness chip** on Profile metrics (contract has no timestamp ⇒ `unknown` ⇒ nothing rendered).
7. ✅ Error path: enable airplane mode → Statistics shows "Métricas indisponíveis" + **Tentar de novo**, not a
   blank "no data".
8. ✅ Locale: numbers render pt-BR (thousands separator per locale).
9. ✅ Accessibility: with TalkBack/VoiceOver, a tile reads as a sentence, e.g. "Publicações: 12".
10. ✅ Text scaling at 200%: tiles grow, nothing clips.
11. ✅ Dark/light: tiles use design tokens in both themes.
12. ✅ Regression: Activity tab still lists real posts; Profile edit still saves (PROFILE-B); feed unaffected.
