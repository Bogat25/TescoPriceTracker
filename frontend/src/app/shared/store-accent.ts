/** Brand-independent accent colour per store, used for chips, badges and chart lines. */
const ACCENTS: Record<string, string> = {
  tesco: '#2563eb',
  auchan: '#db2777',
};

export function storeAccent(storeId: string): string {
  return ACCENTS[storeId] ?? '#64748b';
}
