import { COUNTRIES } from "@/lib/hr/countries";

export type CurrencyEntry = {
  /** ISO 4217 code, e.g. "INR". */
  code: string;
  /** Names of countries using this currency (for search only). */
  countries: string[];
};

/**
 * Deduplicated currency list derived from the country dataset. Currencies
 * shared by many countries appear once; member names are kept so searching
 * "India" finds INR. Sorted by code for a stable, scannable list.
 */
export const CURRENCIES: CurrencyEntry[] = (() => {
  const members = new Map<string, string[]>();
  for (const country of COUNTRIES) {
    if (!country.currency) continue;
    const names = members.get(country.currency);
    if (names) names.push(country.name);
    else members.set(country.currency, [country.name]);
  }
  return [...members.entries()]
    .map(([code, countries]) => ({
      code,
      countries: countries.sort((a, b) => a.localeCompare(b)),
    }))
    .sort((a, b) => a.code.localeCompare(b.code));
})();

export function getCurrencyByCode(code: string): CurrencyEntry | null {
  return CURRENCIES.find((currency) => currency.code === code) ?? null;
}
