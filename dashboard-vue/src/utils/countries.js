// ISO 3166-1 alpha-2 country codes. We store the CODE (matches Stripe, Google Business Profile, and
// schema.org PostalAddress.addressCountry); display names are resolved with Intl.DisplayNames so we don't
// hand-maintain ~250 label strings. normalizeCountry mirrors domain/documents.py normalize_country so legacy
// free-text values ("United States") heal to a code on the client too.

const CODES = [
  "AD","AE","AF","AG","AI","AL","AM","AO","AQ","AR","AS","AT","AU","AW","AX","AZ","BA","BB","BD","BE","BF",
  "BG","BH","BI","BJ","BL","BM","BN","BO","BQ","BR","BS","BT","BV","BW","BY","BZ","CA","CC","CD","CF","CG",
  "CH","CI","CK","CL","CM","CN","CO","CR","CU","CV","CW","CX","CY","CZ","DE","DJ","DK","DM","DO","DZ","EC",
  "EE","EG","EH","ER","ES","ET","FI","FJ","FK","FM","FO","FR","GA","GB","GD","GE","GF","GG","GH","GI","GL",
  "GM","GN","GP","GQ","GR","GS","GT","GU","GW","GY","HK","HM","HN","HR","HT","HU","ID","IE","IL","IM","IN",
  "IO","IQ","IR","IS","IT","JE","JM","JO","JP","KE","KG","KH","KI","KM","KN","KP","KR","KW","KY","KZ","LA",
  "LB","LC","LI","LK","LR","LS","LT","LU","LV","LY","MA","MC","MD","ME","MF","MG","MH","MK","ML","MM","MN",
  "MO","MP","MQ","MR","MS","MT","MU","MV","MW","MX","MY","MZ","NA","NC","NE","NF","NG","NI","NL","NO","NP",
  "NR","NU","NZ","OM","PA","PE","PF","PG","PH","PK","PL","PM","PN","PR","PS","PT","PW","PY","QA","RE","RO",
  "RS","RU","RW","SA","SB","SC","SD","SE","SG","SH","SI","SJ","SK","SL","SM","SN","SO","SR","SS","ST","SV",
  "SX","SY","SZ","TC","TD","TF","TG","TH","TJ","TK","TL","TM","TN","TO","TR","TT","TV","TW","TZ","UA","UG",
  "UM","US","UY","UZ","VA","VC","VE","VG","VI","VN","VU","WF","WS","YE","YT","ZA","ZM","ZW",
];

let regionNames;
function nameFor(code) {
  try {
    if (!regionNames) regionNames = new Intl.DisplayNames(["en"], { type: "region" });
    return regionNames.of(code) || code;
  } catch {
    return code;
  }
}

export const COUNTRIES = CODES.map((code) => ({ code, name: nameFor(code) }))
  .sort((a, b) => a.name.localeCompare(b.name));

const ALIASES = {
  USA: "US", "UNITED STATES": "US", "UNITED STATES OF AMERICA": "US", AMERICA: "US",
  UK: "GB", "UNITED KINGDOM": "GB", "GREAT BRITAIN": "GB", ENGLAND: "GB", SCOTLAND: "GB", WALES: "GB",
};

// Mirror of domain/documents.py normalize_country.
export function normalizeCountry(value) {
  const raw = String(value ?? "").trim();
  if (!raw) return "";
  const key = raw.replace(/\./g, "").toUpperCase().trim();
  if (ALIASES[key]) return ALIASES[key];
  if (/^[A-Z]{2}$/.test(key)) return key;
  return raw;
}
