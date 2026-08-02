import '../../models/hub.dart';

DateTime _minAgo(int m) => DateTime.now().subtract(Duration(minutes: m));
DateTime _hAgo(int h) => DateTime.now().subtract(Duration(hours: h));

CommunityDetail? kCommunityDetail(String id) {
  final bundle = kHubBundle();
  final community =
      bundle.communities.where((c) => c.id == id).cast<Community?>().firstOrNull;
  if (community == null) return null;

  // Slice discussions whose communityHandle matches the community handle.
  final discussions = bundle.discussions
      .where((d) => d.communityHandle == community.handle)
      .toList();

  return CommunityDetail(
    community: community,
    discussions: discussions,
    members: const [
      CommunityMember(
        id: 'mem_001',
        displayName: 'Henrique Tavares',
        username: 'henrique.tavares',
        initials: 'HT',
        accentColor: '#A78BFA',
        roleLabel: 'Moderador',
      ),
      CommunityMember(
        id: 'mem_002',
        displayName: 'Beatriz Lemos',
        username: 'beatriz.lemos',
        initials: 'BL',
        accentColor: '#F59E0B',
        roleLabel: 'Membro',
      ),
      CommunityMember(
        id: 'mem_003',
        displayName: 'Caio Borges',
        username: 'caio.borges',
        initials: 'CB',
        accentColor: '#5BA8FF',
        roleLabel: 'Membro',
      ),
      CommunityMember(
        id: 'mem_004',
        displayName: 'Marina Aragão',
        username: 'marina.aragao',
        initials: 'MA',
        accentColor: '#F59E0B',
        roleLabel: 'Membro',
      ),
    ],
  );
}

extension _FirstOrNull<E> on Iterable<E> {
  E? get firstOrNull => isEmpty ? null : first;
}

HubBundle kHubBundle() => HubBundle(
      communities: [
        const Community(
          id: 'c_brasileirao',
          name: 'Brasileirão',
          handle: '#brasileirao',
          accentColor: '#34D399',
          activeMembers: 4820,
          description: 'Discussões e leituras do campeonato brasileiro.',
        ),
        const Community(
          id: 'c_tatica',
          name: 'Tática',
          handle: '#tatica',
          accentColor: '#A78BFA',
          activeMembers: 812,
          description: 'Análises táticas e movimentações de equipe.',
        ),
        const Community(
          id: 'c_tipsters',
          name: 'Tipsters BR',
          handle: '#tipsters-br',
          accentColor: '#F59E0B',
          activeMembers: 1240,
          description: 'Sinais e leituras independentes.',
        ),
        const Community(
          id: 'c_premier',
          name: 'Premier League',
          handle: '#premier',
          accentColor: '#0EA5E9',
          activeMembers: 1408,
          description: 'Comunidade da liga inglesa.',
        ),
      ],
      tipsters: [
        const Tipster(
          id: 't_analystlab',
          displayName: 'Analyst Lab',
          username: 'analyst.lab',
          accentColor: '#34D399',
          initials: 'AL',
          accuracy: 0.71,
          signals: 312,
          tier: 'Oráculo',
        ),
        const Tipster(
          id: 't_lucas',
          displayName: 'Lucas Scout',
          username: 'lucas.scout',
          accentColor: '#5BA8FF',
          initials: 'LS',
          accuracy: 0.64,
          signals: 184,
          tier: 'Analista',
        ),
        const Tipster(
          id: 't_southsharp',
          displayName: 'South Sharp',
          username: 'south.sharp',
          accentColor: '#A78BFA',
          initials: 'SS',
          accuracy: 0.59,
          signals: 96,
          tier: 'Analista',
        ),
        const Tipster(
          id: 't_marina',
          displayName: 'Marina Aragão',
          username: 'marina.aragao',
          accentColor: '#F59E0B',
          initials: 'MA',
          accuracy: 0.62,
          signals: 142,
          tier: 'Observador',
        ),
      ],
      discussions: [
        Discussion(
          id: 'd_001',
          communityHandle: '#brasileirao',
          authorDisplayName: 'Henrique Tavares',
          authorAccent: '#A78BFA',
          authorInitials: 'HT',
          title: 'Palmeiras x Flamengo — leitura de 2T',
          snippet: 'A reversão de momentum nos últimos 6 minutos…',
          replies: 38,
          lastActivityTs: _minAgo(4),
        ),
        Discussion(
          id: 'd_002',
          communityHandle: '#tatica',
          authorDisplayName: 'Beatriz Lemos',
          authorAccent: '#F59E0B',
          authorInitials: 'BL',
          title: 'Mudança tática Liverpool 4-3-3 → 4-5-1',
          snippet: 'Klopp está blindando — janela alta de gol já passou?',
          replies: 22,
          lastActivityTs: _minAgo(12),
        ),
        Discussion(
          id: 'd_003',
          communityHandle: '#tipsters-br',
          authorDisplayName: 'Caio Borges',
          authorAccent: '#5BA8FF',
          authorInitials: 'CB',
          title: 'Coordenação Under 2.5 ATL × SEV',
          snippet: '4 tipsters independentes postaram sinais parecidos…',
          replies: 19,
          lastActivityTs: _minAgo(24),
        ),
        Discussion(
          id: 'd_004',
          communityHandle: '#premier',
          authorDisplayName: 'Marina Aragão',
          authorAccent: '#F59E0B',
          authorInitials: 'MA',
          title: 'Como a dispersão do consenso revela movimento',
          snippet: 'Vale acompanhar o spread quando há 6+ casas…',
          replies: 14,
          lastActivityTs: _hAgo(2),
        ),
      ],
    );
