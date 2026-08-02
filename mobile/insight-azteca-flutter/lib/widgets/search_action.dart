import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../routing/routes.dart';

/// IconButton that pushes the global search overlay. Place it inside
/// `AppBar.actions` to avoid drift across screens.
class SearchAction extends StatelessWidget {
  const SearchAction({super.key});

  @override
  Widget build(BuildContext context) {
    return IconButton(
      icon: const Icon(Icons.search_rounded),
      tooltip: 'Buscar',
      onPressed: () => context.push(R.search),
    );
  }
}
