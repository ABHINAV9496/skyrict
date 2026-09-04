// Auto-generated from data/codes-all.csv (datasets/country-codes) plus a
// hand-built phone supplement. Do not edit the data by hand - regenerate
// instead.
//
// Provenance per field:
//   code     - CSV column "ISO3166-1-Alpha-2" (rows with an empty code are skipped)
//   name     - CSV column "CLDR display name"
//   currency - first entry of CSV column "ISO4217-currency_alphabetic_code"
//              (comma-separated values take the first; empty -> null)
//   dialCode / phoneMin / phoneMax - hand-built supplement keyed on alpha-2
//              (ITU/libphonenumber-style national significant digit ranges,
//              conservative/wide where variable). Missing supplement rows get
//              explicit nulls; consumers must skip length-locking for them.

export interface CountryEntry {
  /** ISO 3166-1 alpha-2 */
  code: string;
  name: string;
  /** ISO 4217 alphabetic code, or null when the territory has none */
  currency: string | null;
  /** international dial code without the "+", or null when unknown */
  dialCode: string | null;
  /** inclusive national significant digit range, or null when unknown */
  phoneMin: number | null;
  phoneMax: number | null;
}

export const COUNTRIES: CountryEntry[] = [
    { code: "AF", name: "Afghanistan", currency: "AFN", dialCode: "93", phoneMin: 9, phoneMax: 9 },
    { code: "AX", name: "Åland Islands", currency: "EUR", dialCode: "358", phoneMin: 5, phoneMax: 12 },
    { code: "AL", name: "Albania", currency: "ALL", dialCode: "355", phoneMin: 9, phoneMax: 9 },
    { code: "DZ", name: "Algeria", currency: "DZD", dialCode: "213", phoneMin: 8, phoneMax: 9 },
    { code: "AS", name: "American Samoa", currency: "USD", dialCode: "1", phoneMin: 10, phoneMax: 10 },
    { code: "AD", name: "Andorra", currency: "EUR", dialCode: "376", phoneMin: 6, phoneMax: 8 },
    { code: "AO", name: "Angola", currency: "AOA", dialCode: "244", phoneMin: 9, phoneMax: 9 },
    { code: "AI", name: "Anguilla", currency: "XCD", dialCode: "1", phoneMin: 10, phoneMax: 10 },
    { code: "AQ", name: "Antarctica", currency: null, dialCode: null, phoneMin: null, phoneMax: null },
    { code: "AG", name: "Antigua & Barbuda", currency: "XCD", dialCode: "1", phoneMin: 10, phoneMax: 10 },
    { code: "AR", name: "Argentina", currency: "ARS", dialCode: "54", phoneMin: 10, phoneMax: 11 },
    { code: "AM", name: "Armenia", currency: "AMD", dialCode: "374", phoneMin: 8, phoneMax: 8 },
    { code: "AW", name: "Aruba", currency: "AWG", dialCode: "297", phoneMin: 7, phoneMax: 7 },
    { code: "AU", name: "Australia", currency: "AUD", dialCode: "61", phoneMin: 9, phoneMax: 9 },
    { code: "AT", name: "Austria", currency: "EUR", dialCode: "43", phoneMin: 6, phoneMax: 13 },
    { code: "AZ", name: "Azerbaijan", currency: "AZN", dialCode: "994", phoneMin: 9, phoneMax: 9 },
    { code: "BS", name: "Bahamas", currency: "BSD", dialCode: "1", phoneMin: 10, phoneMax: 10 },
    { code: "BH", name: "Bahrain", currency: "BHD", dialCode: "973", phoneMin: 8, phoneMax: 8 },
    { code: "BD", name: "Bangladesh", currency: "BDT", dialCode: "880", phoneMin: 8, phoneMax: 10 },
    { code: "BB", name: "Barbados", currency: "BBD", dialCode: "1", phoneMin: 10, phoneMax: 10 },
    { code: "BY", name: "Belarus", currency: "BYN", dialCode: "375", phoneMin: 9, phoneMax: 9 },
    { code: "BE", name: "Belgium", currency: "EUR", dialCode: "32", phoneMin: 8, phoneMax: 9 },
    { code: "BZ", name: "Belize", currency: "BZD", dialCode: "501", phoneMin: 7, phoneMax: 7 },
    { code: "BJ", name: "Benin", currency: "XOF", dialCode: "229", phoneMin: 8, phoneMax: 8 },
    { code: "BM", name: "Bermuda", currency: "BMD", dialCode: "1", phoneMin: 10, phoneMax: 10 },
    { code: "BT", name: "Bhutan", currency: "INR", dialCode: "975", phoneMin: 8, phoneMax: 8 },
    { code: "BO", name: "Bolivia", currency: "BOB", dialCode: "591", phoneMin: 8, phoneMax: 8 },
    { code: "BA", name: "Bosnia", currency: "BAM", dialCode: "387", phoneMin: 8, phoneMax: 8 },
    { code: "BW", name: "Botswana", currency: "BWP", dialCode: "267", phoneMin: 7, phoneMax: 8 },
    { code: "BV", name: "Bouvet Island", currency: "NOK", dialCode: null, phoneMin: null, phoneMax: null },
    { code: "BR", name: "Brazil", currency: "BRL", dialCode: "55", phoneMin: 10, phoneMax: 11 },
    { code: "IO", name: "British Indian Ocean Territory", currency: "USD", dialCode: null, phoneMin: null, phoneMax: null },
    { code: "VG", name: "British Virgin Islands", currency: "USD", dialCode: "1", phoneMin: 10, phoneMax: 10 },
    { code: "BN", name: "Brunei", currency: "BND", dialCode: "673", phoneMin: 7, phoneMax: 7 },
    { code: "BG", name: "Bulgaria", currency: "EUR", dialCode: "359", phoneMin: 8, phoneMax: 8 },
    { code: "BF", name: "Burkina Faso", currency: "XOF", dialCode: "226", phoneMin: 8, phoneMax: 8 },
    { code: "BI", name: "Burundi", currency: "BIF", dialCode: "257", phoneMin: 8, phoneMax: 8 },
    { code: "KH", name: "Cambodia", currency: "KHR", dialCode: "855", phoneMin: 8, phoneMax: 9 },
    { code: "CM", name: "Cameroon", currency: "XAF", dialCode: "237", phoneMin: 9, phoneMax: 9 },
    { code: "CA", name: "Canada", currency: "CAD", dialCode: "1", phoneMin: 10, phoneMax: 10 },
    { code: "CV", name: "Cape Verde", currency: "CVE", dialCode: "238", phoneMin: 7, phoneMax: 7 },
    { code: "BQ", name: "Caribbean Netherlands", currency: "USD", dialCode: null, phoneMin: null, phoneMax: null },
    { code: "KY", name: "Cayman Islands", currency: "KYD", dialCode: "1", phoneMin: 10, phoneMax: 10 },
    { code: "CF", name: "Central African Republic", currency: "XAF", dialCode: "236", phoneMin: 8, phoneMax: 8 },
    { code: "TD", name: "Chad", currency: "XAF", dialCode: "235", phoneMin: 8, phoneMax: 8 },
    { code: "CL", name: "Chile", currency: "CLP", dialCode: "56", phoneMin: 9, phoneMax: 9 },
    { code: "CN", name: "China", currency: "CNY", dialCode: "86", phoneMin: 9, phoneMax: 11 },
    { code: "CX", name: "Christmas Island", currency: "AUD", dialCode: null, phoneMin: null, phoneMax: null },
    { code: "CC", name: "Cocos Islands", currency: "AUD", dialCode: null, phoneMin: null, phoneMax: null },
    { code: "CO", name: "Colombia", currency: "COP", dialCode: "57", phoneMin: 10, phoneMax: 10 },
    { code: "KM", name: "Comoros", currency: "KMF", dialCode: "269", phoneMin: 7, phoneMax: 7 },
    { code: "CG", name: "Congo - Brazzaville", currency: "XAF", dialCode: "242", phoneMin: 9, phoneMax: 9 },
    { code: "CD", name: "Congo - Kinshasa", currency: "CDF", dialCode: "243", phoneMin: 8, phoneMax: 9 },
    { code: "CK", name: "Cook Islands", currency: "NZD", dialCode: "682", phoneMin: 5, phoneMax: 5 },
    { code: "CR", name: "Costa Rica", currency: "CRC", dialCode: "506", phoneMin: 8, phoneMax: 8 },
    { code: "CI", name: "Côte d’Ivoire", currency: "XOF", dialCode: "225", phoneMin: 8, phoneMax: 10 },
    { code: "HR", name: "Croatia", currency: "EUR", dialCode: "385", phoneMin: 8, phoneMax: 9 },
    { code: "CU", name: "Cuba", currency: "CUP", dialCode: "53", phoneMin: 8, phoneMax: 8 },
    { code: "CW", name: "Curaçao", currency: "XCG", dialCode: "599", phoneMin: 7, phoneMax: 8 },
    { code: "CY", name: "Cyprus", currency: "EUR", dialCode: "357", phoneMin: 8, phoneMax: 8 },
    { code: "CZ", name: "Czechia", currency: "CZK", dialCode: "420", phoneMin: 9, phoneMax: 9 },
    { code: "DK", name: "Denmark", currency: "DKK", dialCode: "45", phoneMin: 8, phoneMax: 8 },
    { code: "DJ", name: "Djibouti", currency: "DJF", dialCode: "253", phoneMin: 8, phoneMax: 8 },
    { code: "DM", name: "Dominica", currency: "XCD", dialCode: "1", phoneMin: 10, phoneMax: 10 },
    { code: "DO", name: "Dominican Republic", currency: "DOP", dialCode: "1", phoneMin: 10, phoneMax: 10 },
    { code: "EC", name: "Ecuador", currency: "USD", dialCode: "593", phoneMin: 8, phoneMax: 9 },
    { code: "EG", name: "Egypt", currency: "EGP", dialCode: "20", phoneMin: 8, phoneMax: 10 },
    { code: "SV", name: "El Salvador", currency: "SVC", dialCode: "503", phoneMin: 8, phoneMax: 8 },
    { code: "GQ", name: "Equatorial Guinea", currency: "XAF", dialCode: "240", phoneMin: 9, phoneMax: 9 },
    { code: "ER", name: "Eritrea", currency: "ERN", dialCode: "291", phoneMin: 7, phoneMax: 7 },
    { code: "EE", name: "Estonia", currency: "EUR", dialCode: "372", phoneMin: 7, phoneMax: 8 },
    { code: "SZ", name: "Eswatini", currency: "SZL", dialCode: "268", phoneMin: 7, phoneMax: 8 },
    { code: "ET", name: "Ethiopia", currency: "ETB", dialCode: "251", phoneMin: 9, phoneMax: 9 },
    { code: "FK", name: "Falkland Islands", currency: "FKP", dialCode: "500", phoneMin: 5, phoneMax: 5 },
    { code: "FO", name: "Faroe Islands", currency: "DKK", dialCode: "298", phoneMin: 6, phoneMax: 6 },
    { code: "FJ", name: "Fiji", currency: "FJD", dialCode: "679", phoneMin: 7, phoneMax: 7 },
    { code: "FI", name: "Finland", currency: "EUR", dialCode: "358", phoneMin: 5, phoneMax: 12 },
    { code: "FR", name: "France", currency: "EUR", dialCode: "33", phoneMin: 9, phoneMax: 9 },
    { code: "GF", name: "French Guiana", currency: "EUR", dialCode: "594", phoneMin: 9, phoneMax: 9 },
    { code: "PF", name: "French Polynesia", currency: "XPF", dialCode: "689", phoneMin: 6, phoneMax: 8 },
    { code: "TF", name: "French Southern Territories", currency: "EUR", dialCode: null, phoneMin: null, phoneMax: null },
    { code: "GA", name: "Gabon", currency: "XAF", dialCode: "241", phoneMin: 7, phoneMax: 8 },
    { code: "GM", name: "Gambia", currency: "GMD", dialCode: "220", phoneMin: 7, phoneMax: 7 },
    { code: "GE", name: "Georgia", currency: "GEL", dialCode: "995", phoneMin: 9, phoneMax: 9 },
    { code: "DE", name: "Germany", currency: "EUR", dialCode: "49", phoneMin: 6, phoneMax: 11 },
    { code: "GH", name: "Ghana", currency: "GHS", dialCode: "233", phoneMin: 9, phoneMax: 9 },
    { code: "GI", name: "Gibraltar", currency: "GIP", dialCode: "350", phoneMin: 8, phoneMax: 8 },
    { code: "GR", name: "Greece", currency: "EUR", dialCode: "30", phoneMin: 10, phoneMax: 10 },
    { code: "GL", name: "Greenland", currency: "DKK", dialCode: "299", phoneMin: 6, phoneMax: 6 },
    { code: "GD", name: "Grenada", currency: "XCD", dialCode: "1", phoneMin: 10, phoneMax: 10 },
    { code: "GP", name: "Guadeloupe", currency: "EUR", dialCode: "590", phoneMin: 9, phoneMax: 9 },
    { code: "GU", name: "Guam", currency: "USD", dialCode: "1", phoneMin: 10, phoneMax: 10 },
    { code: "GT", name: "Guatemala", currency: "GTQ", dialCode: "502", phoneMin: 8, phoneMax: 8 },
    { code: "GG", name: "Guernsey", currency: "GBP", dialCode: "44", phoneMin: 7, phoneMax: 10 },
    { code: "GN", name: "Guinea", currency: "GNF", dialCode: "224", phoneMin: 8, phoneMax: 9 },
    { code: "GW", name: "Guinea-Bissau", currency: "XOF", dialCode: "245", phoneMin: 7, phoneMax: 7 },
    { code: "GY", name: "Guyana", currency: "GYD", dialCode: "592", phoneMin: 7, phoneMax: 7 },
    { code: "HT", name: "Haiti", currency: "HTG", dialCode: "509", phoneMin: 8, phoneMax: 8 },
    { code: "HM", name: "Heard & McDonald Islands", currency: "AUD", dialCode: null, phoneMin: null, phoneMax: null },
    { code: "HN", name: "Honduras", currency: "HNL", dialCode: "504", phoneMin: 8, phoneMax: 8 },
    { code: "HK", name: "Hong Kong", currency: "HKD", dialCode: "852", phoneMin: 8, phoneMax: 8 },
    { code: "HU", name: "Hungary", currency: "HUF", dialCode: "36", phoneMin: 8, phoneMax: 9 },
    { code: "IS", name: "Iceland", currency: "ISK", dialCode: "354", phoneMin: 7, phoneMax: 7 },
    { code: "IN", name: "India", currency: "INR", dialCode: "91", phoneMin: 10, phoneMax: 10 },
    { code: "ID", name: "Indonesia", currency: "IDR", dialCode: "62", phoneMin: 8, phoneMax: 12 },
    { code: "IR", name: "Iran", currency: "IRR", dialCode: "98", phoneMin: 10, phoneMax: 10 },
    { code: "IQ", name: "Iraq", currency: "IQD", dialCode: "964", phoneMin: 10, phoneMax: 10 },
    { code: "IE", name: "Ireland", currency: "EUR", dialCode: "353", phoneMin: 7, phoneMax: 9 },
    { code: "IM", name: "Isle of Man", currency: "GBP", dialCode: "44", phoneMin: 7, phoneMax: 10 },
    { code: "IL", name: "Israel", currency: "ILS", dialCode: "972", phoneMin: 8, phoneMax: 9 },
    { code: "IT", name: "Italy", currency: "EUR", dialCode: "39", phoneMin: 9, phoneMax: 11 },
    { code: "JM", name: "Jamaica", currency: "JMD", dialCode: "1", phoneMin: 10, phoneMax: 10 },
    { code: "JP", name: "Japan", currency: "JPY", dialCode: "81", phoneMin: 9, phoneMax: 10 },
    { code: "JE", name: "Jersey", currency: "GBP", dialCode: "44", phoneMin: 7, phoneMax: 10 },
    { code: "JO", name: "Jordan", currency: "JOD", dialCode: "962", phoneMin: 8, phoneMax: 9 },
    { code: "KZ", name: "Kazakhstan", currency: "KZT", dialCode: "7", phoneMin: 10, phoneMax: 10 },
    { code: "KE", name: "Kenya", currency: "KES", dialCode: "254", phoneMin: 9, phoneMax: 9 },
    { code: "KI", name: "Kiribati", currency: "AUD", dialCode: "686", phoneMin: 5, phoneMax: 8 },
    { code: "KW", name: "Kuwait", currency: "KWD", dialCode: "965", phoneMin: 8, phoneMax: 8 },
    { code: "KG", name: "Kyrgyzstan", currency: "KGS", dialCode: "996", phoneMin: 9, phoneMax: 9 },
    { code: "LA", name: "Laos", currency: "LAK", dialCode: "856", phoneMin: 8, phoneMax: 10 },
    { code: "LV", name: "Latvia", currency: "EUR", dialCode: "371", phoneMin: 8, phoneMax: 8 },
    { code: "LB", name: "Lebanon", currency: "LBP", dialCode: "961", phoneMin: 7, phoneMax: 8 },
    { code: "LS", name: "Lesotho", currency: "LSL", dialCode: "266", phoneMin: 8, phoneMax: 8 },
    { code: "LR", name: "Liberia", currency: "LRD", dialCode: "231", phoneMin: 7, phoneMax: 8 },
    { code: "LY", name: "Libya", currency: "LYD", dialCode: "218", phoneMin: 9, phoneMax: 10 },
    { code: "LI", name: "Liechtenstein", currency: "CHF", dialCode: "423", phoneMin: 7, phoneMax: 7 },
    { code: "LT", name: "Lithuania", currency: "EUR", dialCode: "370", phoneMin: 8, phoneMax: 8 },
    { code: "LU", name: "Luxembourg", currency: "EUR", dialCode: "352", phoneMin: 6, phoneMax: 9 },
    { code: "MO", name: "Macao", currency: "MOP", dialCode: "853", phoneMin: 8, phoneMax: 8 },
    { code: "MG", name: "Madagascar", currency: "MGA", dialCode: "261", phoneMin: 9, phoneMax: 9 },
    { code: "MW", name: "Malawi", currency: "MWK", dialCode: "265", phoneMin: 7, phoneMax: 9 },
    { code: "MY", name: "Malaysia", currency: "MYR", dialCode: "60", phoneMin: 8, phoneMax: 10 },
    { code: "MV", name: "Maldives", currency: "MVR", dialCode: "960", phoneMin: 7, phoneMax: 7 },
    { code: "ML", name: "Mali", currency: "XOF", dialCode: "223", phoneMin: 8, phoneMax: 8 },
    { code: "MT", name: "Malta", currency: "EUR", dialCode: "356", phoneMin: 8, phoneMax: 8 },
    { code: "MH", name: "Marshall Islands", currency: "USD", dialCode: "692", phoneMin: 7, phoneMax: 7 },
    { code: "MQ", name: "Martinique", currency: "EUR", dialCode: "596", phoneMin: 9, phoneMax: 9 },
    { code: "MR", name: "Mauritania", currency: "MRU", dialCode: "222", phoneMin: 8, phoneMax: 8 },
    { code: "MU", name: "Mauritius", currency: "MUR", dialCode: "230", phoneMin: 7, phoneMax: 8 },
    { code: "YT", name: "Mayotte", currency: "EUR", dialCode: "262", phoneMin: 9, phoneMax: 9 },
    { code: "MX", name: "Mexico", currency: "MXN", dialCode: "52", phoneMin: 10, phoneMax: 10 },
    { code: "FM", name: "Micronesia", currency: "USD", dialCode: "691", phoneMin: 7, phoneMax: 7 },
    { code: "MD", name: "Moldova", currency: "MDL", dialCode: "373", phoneMin: 8, phoneMax: 8 },
    { code: "MC", name: "Monaco", currency: "EUR", dialCode: "377", phoneMin: 8, phoneMax: 9 },
    { code: "MN", name: "Mongolia", currency: "MNT", dialCode: "976", phoneMin: 8, phoneMax: 8 },
    { code: "ME", name: "Montenegro", currency: "EUR", dialCode: "382", phoneMin: 8, phoneMax: 8 },
    { code: "MS", name: "Montserrat", currency: "XCD", dialCode: "1", phoneMin: 10, phoneMax: 10 },
    { code: "MA", name: "Morocco", currency: "MAD", dialCode: "212", phoneMin: 9, phoneMax: 9 },
    { code: "MZ", name: "Mozambique", currency: "MZN", dialCode: "258", phoneMin: 8, phoneMax: 9 },
    { code: "MM", name: "Myanmar", currency: "MMK", dialCode: "95", phoneMin: 8, phoneMax: 10 },
    { code: "NA", name: "Namibia", currency: "NAD", dialCode: "264", phoneMin: 7, phoneMax: 10 },
    { code: "NR", name: "Nauru", currency: "AUD", dialCode: "674", phoneMin: 7, phoneMax: 7 },
    { code: "NP", name: "Nepal", currency: "NPR", dialCode: "977", phoneMin: 8, phoneMax: 10 },
    { code: "NL", name: "Netherlands", currency: "EUR", dialCode: "31", phoneMin: 9, phoneMax: 9 },
    { code: "NC", name: "New Caledonia", currency: "XPF", dialCode: "687", phoneMin: 6, phoneMax: 6 },
    { code: "NZ", name: "New Zealand", currency: "NZD", dialCode: "64", phoneMin: 8, phoneMax: 10 },
    { code: "NI", name: "Nicaragua", currency: "NIO", dialCode: "505", phoneMin: 8, phoneMax: 8 },
    { code: "NE", name: "Niger", currency: "XOF", dialCode: "227", phoneMin: 8, phoneMax: 8 },
    { code: "NG", name: "Nigeria", currency: "NGN", dialCode: "234", phoneMin: 8, phoneMax: 10 },
    { code: "NU", name: "Niue", currency: "NZD", dialCode: "683", phoneMin: null, phoneMax: null },
    { code: "NF", name: "Norfolk Island", currency: "AUD", dialCode: "672", phoneMin: null, phoneMax: null },
    { code: "KP", name: "North Korea", currency: "KPW", dialCode: "850", phoneMin: null, phoneMax: null },
    { code: "MK", name: "North Macedonia", currency: "MKD", dialCode: "389", phoneMin: 8, phoneMax: 8 },
    { code: "MP", name: "Northern Mariana Islands", currency: "USD", dialCode: "1", phoneMin: 10, phoneMax: 10 },
    { code: "NO", name: "Norway", currency: "NOK", dialCode: "47", phoneMin: 8, phoneMax: 8 },
    { code: "OM", name: "Oman", currency: "OMR", dialCode: "968", phoneMin: 8, phoneMax: 8 },
    { code: "PK", name: "Pakistan", currency: "PKR", dialCode: "92", phoneMin: 10, phoneMax: 10 },
    { code: "PW", name: "Palau", currency: "USD", dialCode: "680", phoneMin: 7, phoneMax: 7 },
    { code: "PS", name: "Palestine", currency: null, dialCode: "970", phoneMin: 9, phoneMax: 9 },
    { code: "PA", name: "Panama", currency: "PAB", dialCode: "507", phoneMin: 7, phoneMax: 8 },
    { code: "PG", name: "Papua New Guinea", currency: "PGK", dialCode: "675", phoneMin: 8, phoneMax: 8 },
    { code: "PY", name: "Paraguay", currency: "PYG", dialCode: "595", phoneMin: 9, phoneMax: 9 },
    { code: "PE", name: "Peru", currency: "PEN", dialCode: "51", phoneMin: 8, phoneMax: 9 },
    { code: "PH", name: "Philippines", currency: "PHP", dialCode: "63", phoneMin: 10, phoneMax: 10 },
    { code: "PN", name: "Pitcairn", currency: "NZD", dialCode: null, phoneMin: null, phoneMax: null },
    { code: "PL", name: "Poland", currency: "PLN", dialCode: "48", phoneMin: 9, phoneMax: 9 },
    { code: "PT", name: "Portugal", currency: "EUR", dialCode: "351", phoneMin: 9, phoneMax: 9 },
    { code: "PR", name: "Puerto Rico", currency: "USD", dialCode: "1", phoneMin: 10, phoneMax: 10 },
    { code: "QA", name: "Qatar", currency: "QAR", dialCode: "974", phoneMin: 8, phoneMax: 8 },
    { code: "RE", name: "Réunion", currency: "EUR", dialCode: "262", phoneMin: 9, phoneMax: 9 },
    { code: "RO", name: "Romania", currency: "RON", dialCode: "40", phoneMin: 9, phoneMax: 9 },
    { code: "RU", name: "Russia", currency: "RUB", dialCode: "7", phoneMin: 10, phoneMax: 10 },
    { code: "RW", name: "Rwanda", currency: "RWF", dialCode: "250", phoneMin: 9, phoneMax: 9 },
    { code: "WS", name: "Samoa", currency: "WST", dialCode: "685", phoneMin: 5, phoneMax: 7 },
    { code: "SM", name: "San Marino", currency: "EUR", dialCode: "378", phoneMin: 6, phoneMax: 10 },
    { code: "ST", name: "São Tomé & Príncipe", currency: "STN", dialCode: "239", phoneMin: 7, phoneMax: 7 },
    { code: "SA", name: "Saudi Arabia", currency: "SAR", dialCode: "966", phoneMin: 9, phoneMax: 9 },
    { code: "SN", name: "Senegal", currency: "XOF", dialCode: "221", phoneMin: 9, phoneMax: 9 },
    { code: "RS", name: "Serbia", currency: "RSD", dialCode: "381", phoneMin: 8, phoneMax: 9 },
    { code: "SC", name: "Seychelles", currency: "SCR", dialCode: "248", phoneMin: 7, phoneMax: 7 },
    { code: "SL", name: "Sierra Leone", currency: "SLE", dialCode: "232", phoneMin: 8, phoneMax: 8 },
    { code: "SG", name: "Singapore", currency: "SGD", dialCode: "65", phoneMin: 8, phoneMax: 8 },
    { code: "SX", name: "Sint Maarten", currency: "XCG", dialCode: "1", phoneMin: 10, phoneMax: 10 },
    { code: "SK", name: "Slovakia", currency: "EUR", dialCode: "421", phoneMin: 9, phoneMax: 9 },
    { code: "SI", name: "Slovenia", currency: "EUR", dialCode: "386", phoneMin: 8, phoneMax: 8 },
    { code: "SB", name: "Solomon Islands", currency: "SBD", dialCode: "677", phoneMin: 5, phoneMax: 7 },
    { code: "SO", name: "Somalia", currency: "SOS", dialCode: "252", phoneMin: 7, phoneMax: 8 },
    { code: "ZA", name: "South Africa", currency: "ZAR", dialCode: "27", phoneMin: 9, phoneMax: 9 },
    { code: "GS", name: "South Georgia & South Sandwich Islands", currency: null, dialCode: null, phoneMin: null, phoneMax: null },
    { code: "KR", name: "South Korea", currency: "KRW", dialCode: "82", phoneMin: 9, phoneMax: 10 },
    { code: "SS", name: "South Sudan", currency: "SSP", dialCode: "211", phoneMin: 9, phoneMax: 9 },
    { code: "ES", name: "Spain", currency: "EUR", dialCode: "34", phoneMin: 9, phoneMax: 9 },
    { code: "LK", name: "Sri Lanka", currency: "LKR", dialCode: "94", phoneMin: 9, phoneMax: 9 },
    { code: "BL", name: "St. Barthélemy", currency: "EUR", dialCode: "590", phoneMin: 9, phoneMax: 9 },
    { code: "SH", name: "St. Helena", currency: "SHP", dialCode: null, phoneMin: null, phoneMax: null },
    { code: "KN", name: "St. Kitts & Nevis", currency: "XCD", dialCode: "1", phoneMin: 10, phoneMax: 10 },
    { code: "LC", name: "St. Lucia", currency: "XCD", dialCode: "1", phoneMin: 10, phoneMax: 10 },
    { code: "MF", name: "St. Martin", currency: "EUR", dialCode: null, phoneMin: null, phoneMax: null },
    { code: "PM", name: "St. Pierre & Miquelon", currency: "EUR", dialCode: "508", phoneMin: 6, phoneMax: 6 },
    { code: "VC", name: "St. Vincent & Grenadines", currency: "XCD", dialCode: "1", phoneMin: 10, phoneMax: 10 },
    { code: "SD", name: "Sudan", currency: "SDG", dialCode: "249", phoneMin: 9, phoneMax: 9 },
    { code: "SR", name: "Suriname", currency: "SRD", dialCode: "597", phoneMin: 6, phoneMax: 7 },
    { code: "SJ", name: "Svalbard & Jan Mayen", currency: "NOK", dialCode: null, phoneMin: null, phoneMax: null },
    { code: "SE", name: "Sweden", currency: "SEK", dialCode: "46", phoneMin: 7, phoneMax: 13 },
    { code: "CH", name: "Switzerland", currency: "CHF", dialCode: "41", phoneMin: 9, phoneMax: 9 },
    { code: "SY", name: "Syria", currency: "SYP", dialCode: "963", phoneMin: 9, phoneMax: 9 },
    { code: "TW", name: "Taiwan", currency: "TWD", dialCode: "886", phoneMin: 9, phoneMax: 9 },
    { code: "TJ", name: "Tajikistan", currency: "TJS", dialCode: "992", phoneMin: 9, phoneMax: 9 },
    { code: "TZ", name: "Tanzania", currency: "TZS", dialCode: "255", phoneMin: 9, phoneMax: 9 },
    { code: "TH", name: "Thailand", currency: "THB", dialCode: "66", phoneMin: 8, phoneMax: 9 },
    { code: "TL", name: "Timor-Leste", currency: "USD", dialCode: "670", phoneMin: 7, phoneMax: 8 },
    { code: "TG", name: "Togo", currency: "XOF", dialCode: "228", phoneMin: 8, phoneMax: 8 },
    { code: "TK", name: "Tokelau", currency: "NZD", dialCode: null, phoneMin: null, phoneMax: null },
    { code: "TO", name: "Tonga", currency: "TOP", dialCode: "676", phoneMin: 5, phoneMax: 7 },
    { code: "TT", name: "Trinidad & Tobago", currency: "TTD", dialCode: "1", phoneMin: 10, phoneMax: 10 },
    { code: "TN", name: "Tunisia", currency: "TND", dialCode: "216", phoneMin: 8, phoneMax: 8 },
    { code: "TR", name: "Türkiye", currency: null, dialCode: "90", phoneMin: 10, phoneMax: 10 },
    { code: "TM", name: "Turkmenistan", currency: "TMT", dialCode: "993", phoneMin: 8, phoneMax: 8 },
    { code: "TC", name: "Turks & Caicos Islands", currency: "USD", dialCode: "1", phoneMin: 10, phoneMax: 10 },
    { code: "TV", name: "Tuvalu", currency: "AUD", dialCode: "688", phoneMin: 5, phoneMax: 6 },
    { code: "UM", name: "U.S. Outlying Islands", currency: "USD", dialCode: null, phoneMin: null, phoneMax: null },
    { code: "VI", name: "U.S. Virgin Islands", currency: "USD", dialCode: "1", phoneMin: 10, phoneMax: 10 },
    { code: "UG", name: "Uganda", currency: "UGX", dialCode: "256", phoneMin: 9, phoneMax: 9 },
    { code: "UA", name: "Ukraine", currency: "UAH", dialCode: "380", phoneMin: 9, phoneMax: 9 },
    { code: "AE", name: "United Arab Emirates", currency: "AED", dialCode: "971", phoneMin: 8, phoneMax: 9 },
    { code: "GB", name: "United Kingdom", currency: "GBP", dialCode: "44", phoneMin: 7, phoneMax: 10 },
    { code: "US", name: "United States", currency: "USD", dialCode: "1", phoneMin: 10, phoneMax: 10 },
    { code: "UY", name: "Uruguay", currency: "UYU", dialCode: "598", phoneMin: 8, phoneMax: 8 },
    { code: "UZ", name: "Uzbekistan", currency: "UZS", dialCode: "998", phoneMin: 9, phoneMax: 9 },
    { code: "VU", name: "Vanuatu", currency: "VUV", dialCode: "678", phoneMin: 5, phoneMax: 7 },
    { code: "VA", name: "Vatican City", currency: "EUR", dialCode: "39", phoneMin: null, phoneMax: null },
    { code: "VE", name: "Venezuela", currency: "VES", dialCode: "58", phoneMin: 10, phoneMax: 10 },
    { code: "VN", name: "Vietnam", currency: "VND", dialCode: "84", phoneMin: 9, phoneMax: 10 },
    { code: "WF", name: "Wallis & Futuna", currency: "XPF", dialCode: "681", phoneMin: 6, phoneMax: 6 },
    { code: "EH", name: "Western Sahara", currency: "MAD", dialCode: null, phoneMin: null, phoneMax: null },
    { code: "YE", name: "Yemen", currency: "YER", dialCode: "967", phoneMin: 9, phoneMax: 9 },
    { code: "ZM", name: "Zambia", currency: "ZMW", dialCode: "260", phoneMin: 9, phoneMax: 9 },
    { code: "ZW", name: "Zimbabwe", currency: "ZWG", dialCode: "263", phoneMin: 9, phoneMax: 9 },
];

export function getCountryByCode(code: string): CountryEntry | undefined {
  return COUNTRIES.find((country) => country.code === code);
}

/**
 * Dial codes shared by several countries. A stored number only pins the
 * prefix ("+1 415…"), so the tie-break picks the most common owner for the
 * picker's helper text; users can always re-pick a specific country.
 */
const DIAL_CODE_TIE_BREAKS: Record<string, string> = {
  "1": "US", // United States over the other NANP members
  "7": "RU", // Russia over Kazakhstan
  "44": "GB", // United Kingdom over the Crown dependencies
  "47": "NO", // Norway over Svalbard & Jan Mayen
  "358": "FI", // Finland over Åland Islands
};

const MAX_DIAL_CODE_LENGTH = 4;

const DIAL_GROUPS: Map<string, CountryEntry[]> = (() => {
  const groups = new Map<string, CountryEntry[]>();
  for (const country of COUNTRIES) {
    if (country.dialCode === null) continue;
    const bucket = groups.get(country.dialCode);
    if (bucket) bucket.push(country);
    else groups.set(country.dialCode, [country]);
  }
  return groups;
})();

/**
 * Split a stored phone number into its dial-code country and the remainder.
 * Accepts spaced, glued, and punctuated numbers ("+1 415 555 0101",
 * "+14155550101", "+91-98765-43210"); returns null when the value carries no
 * leading "+" or no recognizable dial code.
 */
export function splitDialCode(
  phone: string,
): { country: CountryEntry; rest: string } | null {
  const trimmed = phone.trim();
  if (!trimmed.startsWith("+")) return null;
  const tail = trimmed.slice(1);
  const digits = tail.replace(/[\s\-().]/g, "");
  if (!digits || !/^\d+$/.test(digits)) return null;
  const maxEnd = Math.min(digits.length, MAX_DIAL_CODE_LENGTH);
  for (let end = maxEnd; end >= 1; end--) {
    const bucket = DIAL_GROUPS.get(digits.slice(0, end));
    if (!bucket) continue;
    const preferred = DIAL_CODE_TIE_BREAKS[digits.slice(0, end)];
    const country =
      (preferred ? bucket.find((entry) => entry.code === preferred) : undefined) ??
      bucket[0];
    let seen = 0;
    let index = 0;
    while (index < tail.length && seen < end) {
      if (/\d/.test(tail[index])) seen++;
      index++;
    }
    return { country, rest: tail.slice(index).trim() };
  }
  return null;
}

/** Resolve just the country behind a stored phone number (null if unknown). */
export function matchPhoneCountry(phone: string): CountryEntry | null {
  return splitDialCode(phone)?.country ?? null;
}
