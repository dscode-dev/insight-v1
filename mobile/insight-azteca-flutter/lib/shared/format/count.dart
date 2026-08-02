/// Short count formatter — `42` → "42", `1234` → "1,2k", `42500` → "42k".
///
/// Uses pt-BR comma as the decimal separator.
String formatCount(int n) {
  if (n >= 1000) {
    final k = n / 1000.0;
    final str = k.toStringAsFixed(1).replaceFirst('.', ',');
    return '${str.endsWith(',0') ? str.substring(0, str.length - 2) : str}k';
  }
  return n.toString();
}
