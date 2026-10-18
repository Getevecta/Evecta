/**
 * Location suggestions for “Target location” (cities, regions, countries).
 * value === label. Custom values still allowed in the UI.
 */
const LOCATION_LINES = `
Algeria
Angola
Benin
Botswana
Burkina Faso
Burundi
Cabo Verde
Cameroon
Central African Republic
Chad
Comoros
Democratic Republic of the Congo
Republic of the Congo
Djibouti
Egypt
Equatorial Guinea
Eritrea
Eswatini
Ethiopia
Gabon
Gambia
Ghana
Guinea
Guinea-Bissau
Ivory Coast
Kenya
Lesotho
Liberia
Libya
Madagascar
Malawi
Mali
Mauritania
Mauritius
Morocco
Mozambique
Namibia
Niger
Nigeria
Rwanda
Sao Tome and Principe
Senegal
Seychelles
Sierra Leone
Somalia
South Africa
South Sudan
Sudan
Tanzania
Togo
Tunisia
Uganda
Zambia
Zimbabwe
Africa
Afghanistan
Armenia
Azerbaijan
Bahrain
Bangladesh
Bhutan
Brunei
Cambodia
China
Cyprus
Georgia
India
Indonesia
Iran
Iraq
Israel
Japan
Jordan
Kazakhstan
Kuwait
Kyrgyzstan
Laos
Lebanon
Malaysia
Maldives
Mongolia
Myanmar
Nepal
North Korea
Oman
Pakistan
Palestine
Philippines
Qatar
Saudi Arabia
Singapore
South Korea
Sri Lanka
Syria
Tajikistan
Thailand
Timor-Leste
Turkey
Turkmenistan
United Arab Emirates
Uzbekistan
Vietnam
Yemen
Albania
Andorra
Austria
Belarus
Belgium
Bosnia and Herzegovina
Bulgaria
Croatia
Czech Republic
Denmark
Estonia
Finland
France
Germany
Greece
Hungary
Iceland
Ireland
Italy
Latvia
Liechtenstein
Lithuania
Luxembourg
Malta
Moldova
Monaco
Montenegro
Netherlands
North Macedonia
Norway
Poland
Portugal
Romania
Russia
San Marino
Serbia
Slovakia
Slovenia
Spain
Sweden
Switzerland
Ukraine
United Kingdom
Vatican City
Antigua and Barbuda
Bahamas
Barbados
Belize
Canada
Costa Rica
Cuba
Dominica
Dominican Republic
El Salvador
Grenada
Guatemala
Haiti
Honduras
Jamaica
Mexico
Nicaragua
Panama
Saint Kitts and Nevis
Saint Lucia
Saint Vincent and the Grenadines
Trinidad and Tobago
United States
Argentina
Bolivia
Brazil
Chile
Colombia
Ecuador
Guyana
Paraguay
Peru
Suriname
Uruguay
Venezuela
Australia
Fiji
Kiribati
Marshall Islands
Micronesia
Nauru
New Zealand
Palau
Papua New Guinea
Samoa
Solomon Islands
Tonga
Tuvalu
Vanuatu
UAE
UK
USA
Hong Kong
Taiwan
Ahmedabad
Asia Pacific
Australia & New Zealand
Bangalore
Bangkok
Barcelona
Beijing
Berlin
Birmingham
Boston
Bristol
Brussels
Buenos Aires
Cairo
California
Chennai
Chicago
Coimbatore
Dallas
Delhi NCR
Dubai
Dublin
Edinburgh
Europe
Frankfurt
Global
Gurugram
Hyderabad
Indore
Istanbul
Jaipur
Jakarta
Johannesburg
Kathmandu
Pokhara
Lalitpur
Bhaktapur
Kochi
Kolkata
Colombo
Dhaka
Chittagong
Lahore
Karachi
Islamabad
Hanoi
Ho Chi Minh City
Phnom Penh
Yangon
London
Los Angeles
Madrid
Manchester
Melbourne
Mexico City
Miami
Montreal
Mumbai
Munich
Nairobi
Nashik
New Delhi
New York
Noida
North America
Oceania
Paris
Perth
Philadelphia
Pune
Riyadh
Rome
San Francisco
Santiago
São Paulo
Seattle
Seoul
Shanghai
Silicon Valley
Singapore City
Stockholm
Sydney
Tel Aviv
Tokyo
Toronto
United States — East Coast
United States — West Coast
Vadodara
Vancouver
Visakhapatnam
Warsaw
Washington DC
Zurich
Americas
Asia
Europe
Middle East
Latin America
Scandinavia
Worldwide
Remote / Global
Other
`;

function parsePresetLabels(): string[] {
  const labels = LOCATION_LINES.trim()
    .split(/\n/)
    .map((s) => s.trim())
    .filter(Boolean);
  return [...new Set(labels)].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
}

export const PROFILE_LOCATION_PRESET_LABELS: readonly string[] = parsePresetLabels();
