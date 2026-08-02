// Legal constants + in-app legal documents.
//
// The policies are bundled in the app so Store Review can access them offline.

import 'package:flutter/material.dart';

import '../shared/extensions/build_context_x.dart';
import '../theme/spacing.dart';
import '../widgets/insight_bottom_sheet.dart';

// AZTECA-QUALITY-A: legal/store-facing organization corrected to AllBlue-Labs
// (the App Store / Play publisher). A material ownership change to the Terms +
// Privacy documents ⇒ versions bumped (re-triggers EULA acceptance at register,
// which records `accepted_terms_version`) and effective date refreshed.
const String kTermsVersion = '1.2';
const String kPrivacyVersion = '1.2';
const String kUgcPolicyVersion = '1.0';
const String kLegalEffectiveDate = '04/07/2026';

// NOTE (AZTECA-QUALITY-A): these contact addresses still use the konohalabs.com.br
// infrastructure domain. The legal OWNER is AllBlue-Labs; the support/moderation
// mailbox domain must be confirmed by the org before switching (an invented
// address would route users nowhere). Tracked as a decision in
// docs/azteca-quality-a/AZTECA_QUALITY_A_LEGAL_CHANGES.md — do not fabricate.
const String kSupportEmail = 'suporte@konohalabs.com.br';
const String kModerationEmail = 'moderacao@konohalabs.com.br';

enum LegalDocumentKind { terms, privacy, ugc }

class LegalSection {
  const LegalSection(this.title, this.body);
  final String title;
  final String body;
}

class LegalDocument {
  const LegalDocument({
    required this.kind,
    required this.title,
    required this.version,
    required this.updatedAt,
    required this.summary,
    required this.sections,
  });

  final LegalDocumentKind kind;
  final String title;
  final String version;
  final String updatedAt;
  final String summary;
  final List<LegalSection> sections;
}

const LegalDocument kTermsDocument = LegalDocument(
  kind: LegalDocumentKind.terms,
  title: 'Termos de Uso',
  version: kTermsVersion,
  updatedAt: kLegalEffectiveDate,
  summary:
      'Regras para usar o Insight, publicar conteúdo, interagir com pessoas e acessar inteligência esportiva.',
  sections: [
    LegalSection(
      '1. Plataforma',
      'O Insight é uma plataforma de inteligência social esportiva. O app combina perfis, comunidades, discussões, sinais, comentários e conteúdo editorial ou automatizado para ajudar usuários a acompanhar futebol e conversas esportivas.',
    ),
    LegalSection(
      '2. Elegibilidade',
      'Você deve ter idade legal para criar conta no seu país ou autorização do responsável legal. Ao criar a conta, você declara que pode aceitar estes Termos e usar o serviço de forma responsável.',
    ),
    LegalSection(
      '3. Conta e responsabilidade',
      'Você é responsável por manter seu telefone, sessão e dispositivo seguros. Qualquer atividade feita pela sua conta pode ser atribuída a você, salvo falha comprovada de segurança do serviço.',
    ),
    LegalSection(
      '4. Uso aceitável',
      'Você não pode usar o Insight para atividade ilegal, abuso, fraude, spam, manipulação de métricas, engenharia reversa indevida, coleta automatizada não autorizada ou tentativa de burlar moderação, bloqueios e limites técnicos.',
    ),
    LegalSection(
      '5. Conteúdo gerado por usuários',
      'Publicações, comentários, nomes, biografias, imagens e interações são responsabilidade de quem publica. Você deve ter direito de publicar o material e não pode violar direitos de terceiros.',
    ),
    LegalSection(
      '6. Tolerância zero',
      'O Insight proíbe assédio, ameaças, discurso de ódio, pornografia ou conteúdo sexual explícito, exploração de menores, violência gráfica, doxxing, golpes, fraude, spam, incitação à violência e qualquer conteúdo ilegal. Violações podem gerar remoção imediata e banimento.',
    ),
    LegalSection(
      '7. Moderação',
      'Podemos revisar, ocultar, reduzir alcance, remover conteúdo, suspender contas, banir usuários e preservar registros quando necessário para segurança, investigação, cumprimento legal ou integridade da comunidade.',
    ),
    LegalSection(
      '8. Denúncia e bloqueio',
      'Você pode denunciar publicações pelo menu de três pontos e perfis pela tela de perfil. Você também pode bloquear usuários para reduzir interações indesejadas. Denúncias são avaliadas conforme gravidade, contexto e histórico.',
    ),
    LegalSection(
      '9. Inteligência esportiva e IA',
      'Conteúdos, sinais, análises, rankings e informações geradas ou assistidas por IA podem conter erros, atrasos ou inferências incompletas. Eles são informativos e não substituem julgamento humano.',
    ),
    LegalSection(
      '10. Apostas',
      'O Insight não oferece recomendação de aposta, aconselhamento financeiro, garantia de resultado esportivo ou incentivo para apostar. Qualquer decisão externa ao app é de responsabilidade do usuário.',
    ),
    LegalSection(
      '11. Disponibilidade',
      'O serviço pode sofrer manutenção, instabilidade, indisponibilidade, mudanças de recursos ou limitações temporárias. Faremos esforços razoáveis para manter a plataforma operante.',
    ),
    LegalSection(
      '12. Limitação de responsabilidade',
      'Na máxima extensão permitida por lei, o Insight e a AllBlue-Labs não respondem por perdas indiretas, lucros cessantes, decisões tomadas com base em conteúdo do app ou conduta de terceiros.',
    ),
    LegalSection(
      '13. Alterações',
      'Podemos atualizar estes Termos. Mudanças materiais exigirão novo aceite ou aviso destacado no app. A versão aceita no cadastro é registrada quando suportado pelo backend.',
    ),
    LegalSection(
      '14. Suporte',
      'Suporte: $kSupportEmail\nModeração e segurança: $kModerationEmail',
    ),
  ],
);

const LegalDocument kPrivacyDocument = LegalDocument(
  kind: LegalDocumentKind.privacy,
  title: 'Política de Privacidade',
  version: kPrivacyVersion,
  updatedAt: kLegalEffectiveDate,
  summary:
      'Como o Insight coleta, usa, protege, compartilha e exclui dados pessoais, incluindo direitos LGPD.',
  sections: [
    LegalSection(
      '1. Controlador',
      'A AllBlue-Labs é a controladora dos dados tratados pelo Insight. Contato para privacidade e suporte: $kSupportEmail.',
    ),
    LegalSection(
      '2. Dados coletados',
      'Coletamos número de telefone, identificadores de conta, nome de usuário, nome exibido, avatar opcional, configurações, sessões, refresh tokens, idioma, preferências e registros necessários para operar o app.',
    ),
    LegalSection(
      '3. Autenticação por telefone',
      'Usamos seu número de telefone para enviar e validar código OTP. O provedor de autenticação confirma a posse do número; identidade, sessão e permissões do Insight continuam sob controle do Insight.',
    ),
    LegalSection(
      '4. Conteúdo e perfil',
      'Tratamos publicações, comentários, curtidas, seguidores, bloqueios, comunidades, discussões, sinais e outros dados sociais para exibir o produto, manter histórico e operar recursos escolhidos por você.',
    ),
    LegalSection(
      '5. Moderação e segurança',
      'Podemos tratar denúncias, motivos, evidências, bloqueios, logs de moderação, decisões de revisão, suspensões e histórico de abuso para proteger usuários e cumprir obrigações legais.',
    ),
    LegalSection(
      '6. Dispositivo e diagnósticos',
      'Podemos coletar dados técnicos como versão do app, sistema operacional, idioma, erros, desempenho, endereços de rede e metadados de requisições para segurança, suporte e estabilidade.',
    ),
    LegalSection(
      '7. Analytics',
      'Se analytics forem habilitados no futuro, usaremos dados agregados ou pseudonimizados para entender estabilidade, funis e qualidade do produto. Não vendemos dados pessoais.',
    ),
    LegalSection(
      '8. Bases legais LGPD',
      'Tratamos dados com base em execução de contrato, legítimo interesse, cumprimento legal, proteção contra fraude, exercício regular de direitos e consentimento quando aplicável.',
    ),
    LegalSection(
      '9. Retenção',
      'Mantemos dados enquanto a conta existir ou pelo prazo necessário para segurança, auditoria, disputas, cumprimento legal e prevenção de abuso. Conteúdos removidos podem permanecer em logs por período limitado.',
    ),
    LegalSection(
      '10. Compartilhamento',
      'Compartilhamos dados com provedores essenciais, como infraestrutura, banco de dados, envio de OTP, observabilidade, segurança e suporte. Esses subprocessadores devem tratar dados conforme instruções e medidas de segurança.',
    ),
    LegalSection(
      '11. Direitos do usuário',
      'Você pode pedir confirmação de tratamento, acesso, correção, portabilidade, exclusão, anonimização, informações sobre compartilhamento, revisão de decisões e revogação de consentimento quando aplicável.',
    ),
    LegalSection(
      '12. Exclusão e exportação',
      'Solicitações de exclusão ou exportação podem ser feitas por $kSupportEmail. Podemos precisar confirmar sua identidade e manter dados exigidos por lei, segurança ou defesa de direitos.',
    ),
    LegalSection(
      '13. Menores',
      'O Insight não é destinado a crianças. Se identificarmos conta criada por menor sem autorização exigida, poderemos limitar, suspender ou excluir a conta.',
    ),
    LegalSection(
      '14. Segurança',
      'Aplicamos controles técnicos e organizacionais como autenticação, tokens, segregação de acesso, logs, revisão de incidentes e boas práticas de infraestrutura. Nenhum sistema é totalmente imune a riscos.',
    ),
    LegalSection(
      '15. Contato',
      'Privacidade e suporte: $kSupportEmail\nModeração e segurança: $kModerationEmail',
    ),
  ],
);

const LegalDocument kUgcSafetyDocument = LegalDocument(
  kind: LegalDocumentKind.ugc,
  title: 'Política de Segurança UGC',
  version: kUgcPolicyVersion,
  updatedAt: kLegalEffectiveDate,
  summary:
      'Regras de segurança para publicações, perfis, denúncias, bloqueios e revisão de moderação.',
  sections: [
    LegalSection(
      '1. O que não pode ser publicado',
      'Não publique assédio, ameaças, ódio, pornografia, exploração sexual, violência gráfica, doxxing, informações privadas, fraude, phishing, spam, manipulação, conteúdo ilegal ou material que viole direitos de terceiros.',
    ),
    LegalSection(
      '2. Denunciar publicações',
      'Abra o menu de três pontos da publicação, escolha Denunciar, selecione o motivo e envie detalhes quando possível. Denúncias ajudam a priorizar revisão.',
    ),
    LegalSection(
      '3. Denunciar perfis',
      'Na tela de perfil, use o menu de ações para denunciar comportamento, identidade falsa, abuso recorrente ou risco de segurança.',
    ),
    LegalSection(
      '4. Bloquear usuários',
      'Bloquear reduz a visibilidade e interações daquele usuário para você. O bloqueio não substitui denúncia quando houver risco, abuso ou violação das regras.',
    ),
    LegalSection(
      '5. Revisão de moderação',
      'Denúncias podem ser revisadas por sistemas automatizados, sinais de segurança e revisores humanos. Consideramos contexto, gravidade, reincidência, risco imediato e evidências disponíveis.',
    ),
    LegalSection(
      '6. Medidas aplicáveis',
      'Podemos remover conteúdo, limitar distribuição, ocultar comentários, advertir usuários, suspender contas, banir permanentemente, preservar evidências e cooperar com autoridades quando exigido.',
    ),
    LegalSection(
      '7. Contato de revisão',
      'Para contestar moderação, relatar risco urgente ou pedir revisão humana, contate $kModerationEmail. Para suporte geral, use $kSupportEmail.',
    ),
  ],
);

const List<LegalDocument> kLegalDocuments = [
  kTermsDocument,
  kPrivacyDocument,
  kUgcSafetyDocument,
];

Future<void> showTermsOfUse(BuildContext context) =>
    showLegalDocument(context, kTermsDocument);

Future<void> showPrivacyPolicy(BuildContext context) =>
    showLegalDocument(context, kPrivacyDocument);

Future<void> showUgcSafetyPolicy(BuildContext context) =>
    showLegalDocument(context, kUgcSafetyDocument);

Future<void> showLegalCenter(BuildContext context) {
  return showInsightBottomSheet<void>(
    context: context,
    builder: (ctx) => InsightBottomSheet(
      title: 'Central legal',
      subtitle: 'Políticas do Insight disponíveis offline no app.',
      maxHeightFactor: 0.86,
      children: [
        for (final doc in kLegalDocuments) ...[
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: Text(doc.title),
            subtitle: Text(
              'Versão ${doc.version} · Atualizado em ${doc.updatedAt}',
              style: ctx.tt.bodySmall?.copyWith(color: ctx.ds.textLow),
            ),
            trailing: const Icon(Icons.chevron_right_rounded),
            onTap: () => showLegalDocument(ctx, doc),
          ),
          const Divider(height: 1),
        ],
        const SizedBox(height: InsightSpacing.lg),
      ],
    ),
  );
}

Future<void> showLegalDocument(BuildContext context, LegalDocument document) {
  final keys = [for (final _ in document.sections) GlobalKey()];
  final controller = ScrollController();

  Future<void> jumpTo(int index) async {
    final currentContext = keys[index].currentContext;
    if (currentContext == null) return;
    await Scrollable.ensureVisible(
      currentContext,
      duration: const Duration(milliseconds: 260),
      curve: Curves.easeOutCubic,
      alignment: 0.08,
    );
  }

  return showInsightBottomSheet<void>(
    context: context,
    builder: (ctx) => InsightBottomSheet(
      title: document.title,
      subtitle:
          'Versão ${document.version} · Atualizado em ${document.updatedAt}',
      maxHeightFactor: 0.94,
      children: [
        Text(
          document.summary,
          style: ctx.tt.bodyMedium?.copyWith(
            color: ctx.ds.textMid,
            height: 1.35,
          ),
        ),
        const SizedBox(height: InsightSpacing.md),
        SizedBox(
          height: 38,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            itemCount: document.sections.length,
            separatorBuilder: (_, __) => const SizedBox(width: 8),
            itemBuilder: (_, index) => ActionChip(
              label: Text('${index + 1}'),
              tooltip: document.sections[index].title,
              onPressed: () => jumpTo(index),
            ),
          ),
        ),
        const SizedBox(height: InsightSpacing.lg),
        ConstrainedBox(
          constraints: BoxConstraints(
            maxHeight: MediaQuery.sizeOf(ctx).height * 0.58,
          ),
          child: Scrollbar(
            controller: controller,
            thumbVisibility: true,
            child: ListView.separated(
              controller: controller,
              shrinkWrap: true,
              itemCount: document.sections.length,
              separatorBuilder: (_, __) =>
                  const SizedBox(height: InsightSpacing.lg),
              itemBuilder: (_, index) {
                final section = document.sections[index];
                return _LegalSectionView(key: keys[index], section: section);
              },
            ),
          ),
        ),
        const SizedBox(height: InsightSpacing.xl2),
      ],
    ),
  );
}

class _LegalSectionView extends StatelessWidget {
  const _LegalSectionView({super.key, required this.section});
  final LegalSection section;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      header: true,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(section.title, style: context.tt.titleMedium),
          const SizedBox(height: InsightSpacing.xs),
          Text(
            section.body,
            style: context.tt.bodyMedium?.copyWith(height: 1.45),
          ),
        ],
      ),
    );
  }
}
