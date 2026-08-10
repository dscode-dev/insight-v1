--
-- REMINDERS-V1 — operational deadlines the console can show before they bite.
--
-- The immediate cause is the mTLS pair the Gateway and Social now use, which
-- expires in November 2028. A certificate that lapses does not degrade: the
-- gRPC link stops, the whole social API with it, and the message an operator
-- sees says nothing about a date.
--
-- TWO KINDS, AND THE DIFFERENCE IS THE WHOLE DESIGN.
--
--   DERIVED — the deadline is a property of a real artefact. A certificate's
--   notAfter, a token's expiry. Nobody types it; whatever owns the artefact
--   REPORTS it, and the reminder is only ever as stale as the last report.
--
--   DECLARED — the deadline is a policy. "Rotate the Cloudflare service token
--   every 90 days." There is no artefact to read; the operator states the
--   period and records when it was last done.
--
-- WHY A TYPED DATE WOULD HAVE BEEN WRONG FOR THE FIRST KIND. If an operator
-- types "certificate expires 2028-11-10" and then rotates the certificate,
-- the reminder still says 2028 — pointing at a date that stopped being true
-- the moment the thing it describes changed. A derived reminder cannot drift,
-- because it holds no date of its own: it holds the last one reported, plus
-- when that report happened.
--
-- WHY REPORTED AND NOT POLLED. The certificates live on the GCloud VM; this
-- database is on the Robozão, and the Control Plane cannot read files there.
-- Inverting it — the host that owns the artefact pushes what it observes —
-- also means adding a new artefact never requires teaching the console how to
-- reach a new place.
--
CREATE TABLE IF NOT EXISTS control_plane.operational_reminders (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug         TEXT NOT NULL UNIQUE,
    title        TEXT NOT NULL,
    -- What breaks when this lapses, in the operator's words. A reminder whose
    -- consequence is unstated gets postponed by whoever is on call.
    impact       TEXT NOT NULL,
    kind         TEXT NOT NULL,

    -- DERIVED: filled by whatever owns the artefact, via the report endpoint.
    observed_expires_at TIMESTAMPTZ,
    observed_at         TIMESTAMPTZ,
    observed_detail     TEXT,

    -- DECLARED: the operator's policy.
    period_days  INTEGER,
    last_done_at TIMESTAMPTZ,

    -- How long before the deadline this should start showing as due. A
    -- certificate needs weeks (someone must generate, deploy and verify a new
    -- one); a token rotation needs a day.
    lead_days    INTEGER NOT NULL DEFAULT 30,

    -- Muted rather than deleted: an operator who has decided a reminder is
    -- noise should leave a trace of that decision, not remove the row and
    -- have someone recreate it in six months.
    muted_until  TIMESTAMPTZ,
    notes        TEXT,

    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by   TEXT,

    CONSTRAINT operational_reminders_kind_check
        CHECK (kind IN ('derived', 'declared')),
    -- A declared reminder with no period cannot compute a next date, and a
    -- derived one with a typed period would be inventing the thing it exists
    -- to avoid inventing.
    CONSTRAINT operational_reminders_declared_needs_period
        CHECK (kind <> 'declared' OR period_days IS NOT NULL),
    CONSTRAINT operational_reminders_derived_has_no_period
        CHECK (kind <> 'derived' OR period_days IS NULL),
    CONSTRAINT operational_reminders_period_range
        CHECK (period_days IS NULL OR period_days BETWEEN 1 AND 3650),
    CONSTRAINT operational_reminders_lead_range
        CHECK (lead_days BETWEEN 0 AND 365)
);

CREATE INDEX IF NOT EXISTS ix_operational_reminders_kind
    ON control_plane.operational_reminders (kind);

--
-- The due date, in one place.
--
-- A FUNCTION rather than a column: a stored `due_at` is a cached answer that
-- goes stale the moment a report arrives or a rotation is recorded, and every
-- reader would have to know whether it had been refreshed. Computing it makes
-- the answer a property of the current row.
--
CREATE OR REPLACE FUNCTION control_plane.reminder_due_at(
    p_kind TEXT,
    p_observed_expires_at TIMESTAMPTZ,
    p_period_days INTEGER,
    p_last_done_at TIMESTAMPTZ
) RETURNS TIMESTAMPTZ
LANGUAGE sql IMMUTABLE AS
$$
    SELECT CASE
        WHEN p_kind = 'derived' THEN p_observed_expires_at
        -- A declared reminder that has never been done is due now: it was
        -- created because something needs doing, and treating "no record" as
        -- "no deadline" would hide exactly the ones nobody has started.
        WHEN p_last_done_at IS NULL THEN now()
        ELSE p_last_done_at + make_interval(days => p_period_days)
    END
$$;

--
-- Seeded with what this session actually produced. Real deadlines, not
-- examples: an empty reminders page teaches an operator that the feature is
-- decorative.
--
INSERT INTO control_plane.operational_reminders
    (slug, title, impact, kind, lead_days, notes)
VALUES
    ('mtls-social-cert',
     'Certificado mTLS do insight-social',
     'Vencido, o gRPC entre Gateway e Social para e toda a API social cai. '
     'O erro que aparece nao menciona data.',
     'derived', 45,
     'Emitido pela CA interna em /home/insight/Insight/configs/mtls na VM do GCloud. '
     'Reportado por quem detem o arquivo; nao e digitado aqui.'),
    ('mtls-gateway-cert',
     'Certificado mTLS do insight-gateway',
     'Mesmo efeito: o Gateway deixa de autenticar no Social e o BFF nao registra rotas.',
     'derived', 45,
     'Par do anterior, mesma CA.'),
    ('mtls-internal-ca',
     'CA interna (raiz do mTLS)',
     'Rotacionar a CA exige tocar os dois servicos ao mesmo tempo — '
     'a unica operacao que este desenho torna cara.',
     'derived', 90,
     'Validade longa por isso mesmo.')
ON CONFLICT (slug) DO NOTHING;

INSERT INTO control_plane.operational_reminders
    (slug, title, impact, kind, period_days, lead_days, notes)
VALUES
    ('cloudflare-service-token',
     'Rotacionar o service token do Cloudflare Access',
     'E a credencial que autentica o Control Plane na borda do tunel. '
     'Comprometida, da acesso a superficie administrativa do Social.',
     'declared', 90, 7,
     'Zero Trust -> Access -> Service Auth. Trocar tambem CF_ACCESS_CLIENT_ID '
     'e CF_ACCESS_CLIENT_SECRET no .env do Robozao.'),
    ('cloudflare-tunnel-token',
     'Rotacionar o token do conector do tunel',
     'Permite registrar um conector como sendo este tunel.',
     'declared', 180, 7,
     'Zero Trust -> Networks -> Tunnels -> insight-console -> Configure.'),
    ('social-ops-token',
     'Rotacionar o SOCIAL_OPS_TOKEN',
     'Autoriza o Control Plane no plano administrativo do Social. '
     'Independente do Access: passar pelo tunel nao substitui este token.',
     'declared', 180, 7,
     'Precisa ser identico no .env da VM do GCloud e no do Robozao.')
ON CONFLICT (slug) DO NOTHING;
