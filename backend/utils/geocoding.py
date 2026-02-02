"""
City/state → lat/lon geocoding using a hardcoded coordinate lookup.

Handles both full state names ("California") and 2-letter codes ("CA").
"""

from typing import Optional, Tuple

from backend.utils.state_normalizer import get_state_name

CITY_COORDS = {
    # Major cities
    "Chicago, Illinois": (41.8781, -87.6298),
    "Los Angeles, California": (34.0522, -118.2437),
    "Minneapolis, Minnesota": (44.9778, -93.2650),
    "New York, New York": (40.7128, -74.0060),
    "New York City, New York": (40.7128, -74.0060),
    "Portland, Oregon": (45.5152, -122.6784),
    "San Francisco, California": (37.7749, -122.4194),
    "Seattle, Washington": (47.6062, -122.3321),
    "Newark, New Jersey": (40.7357, -74.1724),
    "Denver, Colorado": (39.7392, -104.9903),
    "Phoenix, Arizona": (33.4484, -112.0740),
    "Houston, Texas": (29.7604, -95.3698),
    "Dallas, Texas": (32.7767, -96.7970),
    "Austin, Texas": (30.2672, -97.7431),
    "Atlanta, Georgia": (33.7490, -84.3880),
    "Miami, Florida": (25.7617, -80.1918),
    "Boston, Massachusetts": (42.3601, -71.0589),
    "Philadelphia, Pennsylvania": (39.9526, -75.1652),
    "San Diego, California": (32.7157, -117.1611),
    "Oakland, California": (37.8044, -122.2712),
    "Sacramento, California": (38.5816, -121.4944),
    "San Antonio, Texas": (29.4241, -98.4936),
    "El Paso, Texas": (31.7619, -106.4850),
    "Tucson, Arizona": (32.2226, -110.9747),
    "Washington, District of Columbia": (38.9072, -77.0369),
    "Washington DC, District of Columbia": (38.9072, -77.0369),
    "Baltimore, Maryland": (39.2904, -76.6122),
    "Detroit, Michigan": (42.3314, -83.0458),
    "Las Vegas, Nevada": (36.1699, -115.1398),
    "North Las Vegas, Nevada": (36.1989, -115.1175),
    "Milwaukee, Wisconsin": (43.0389, -87.9065),
    "Albuquerque, New Mexico": (35.0844, -106.6504),
    # California cities
    "Paramount, California": (33.8894, -118.1597),
    "Northridge, Los Angeles, California": (34.2283, -118.5366),
    "Adelanto, California": (34.5828, -117.4092),
    "Van Nuys, California": (34.1897, -118.4514),
    "Santa Ana, California": (33.7455, -117.8677),
    "Montclair, California": (34.0775, -117.6897),
    "San Bernardino, California": (34.1083, -117.2898),
    "Ontario, California": (34.0633, -117.6509),
    "Camarillo, California": (34.2164, -119.0376),
    "Bakersfield, California": (35.3733, -119.0187),
    "Encinitas, California": (33.0370, -117.2920),
    "Chula Vista, California": (32.6401, -117.0842),
    "Glendale, California": (34.1425, -118.2551),
    "Highland, California": (34.1283, -117.2086),
    "Dublin, California": (37.7022, -121.9358),
    "Monrovia, California": (34.1442, -117.9990),
    # Texas cities
    "Alvarado, Texas": (32.4068, -97.2128),
    "McAllen, Texas": (26.2034, -98.2300),
    "Laredo, Texas": (27.5064, -99.5075),
    "Rio Grande City (Starr County), Texas": (26.3796, -98.8203),
    "Sarita, Texas": (27.2214, -97.7886),
    "Dallas-Fort Worth, Texas": (32.8998, -97.0403),
    "Dilley, Texas": (28.6674, -99.1706),
    # Illinois cities
    "Broadview, Illinois": (41.8639, -87.8534),
    "Franklin Park, Illinois": (41.9314, -87.8656),
    "Elgin, Illinois": (42.0354, -88.2825),
    "Lyons, Illinois": (41.8131, -87.8181),
    "Rockford, Illinois": (42.2711, -89.0940),
    # Minnesota cities
    "Minneapolis (26th & Nicollet), Minnesota": (44.9578, -93.2780),
    "Minneapolis (Federal Building), Minnesota": (44.9765, -93.2680),
    "St. Paul, Minnesota": (44.9537, -93.0900),
    "Hopkins, Minnesota": (44.9252, -93.4183),
    "Crystal (Robbinsdale), Minnesota": (45.0322, -93.3599),
    "Minneapolis-St. Paul Airport, Minnesota": (44.8848, -93.2223),
    "Rosemount, Minnesota": (44.7394, -93.1258),
    # Other state cities
    "Aurora, Colorado": (39.7294, -104.8319),
    "Colorado Springs, Colorado": (38.8339, -104.8214),
    "Durango, Colorado": (37.2753, -107.8801),
    "Tacoma, Washington": (47.2529, -122.4443),
    "SeaTac, Washington": (47.4435, -122.2961),
    "Bellingham, Washington": (48.7519, -122.4787),
    "Spokane, Washington": (47.6588, -117.4260),
    "San Jose, California": (37.3382, -121.8863),
    "Fresno, California": (36.7378, -119.7871),
    "Fort Bliss, Texas": (31.8134, -106.4224),
    "Lumpkin, Georgia": (32.0507, -84.7991),
    "Eloy, Arizona": (32.7559, -111.5548),
    "Norfolk, Virginia": (36.8508, -76.2859),
    "San Juan, Puerto Rico": (18.4655, -66.1057),
    "Rolla, Missouri": (37.9514, -91.7712),
    "Pompano Beach, Florida": (26.2379, -80.1248),
    "Valdosta, Georgia": (30.8327, -83.2785),
    "Karnes City, Texas": (28.8850, -97.9006),
    "Florence, Arizona": (33.0314, -111.3873),
    "Victorville, California": (34.5362, -117.2928),
    "Conroe, Texas": (30.3119, -95.4561),
    "Calexico, California": (32.6789, -115.4989),
    "Orlando, Florida": (28.5383, -81.3792),
    "Tampa, Florida": (27.9506, -82.4572),
    "Jacksonville, Florida": (30.3322, -81.6557),
    "Charlotte, North Carolina": (35.2271, -80.8431),
    "Salisbury, North Carolina": (35.6708, -80.4742),
    "Des Moines, Iowa": (41.5868, -93.6250),
    "Iowa City, Iowa": (41.6611, -91.5302),
    "Fitchburg, Massachusetts": (42.5834, -71.8023),
    "Medford, Massachusetts": (42.4184, -71.1062),
    "Worcester, Massachusetts": (42.2626, -71.8023),
    "Oklahoma City, Oklahoma": (35.4676, -97.5164),
    "Liberty, Missouri": (39.2461, -94.4191),
    "St. Peters, Missouri": (38.8004, -90.6265),
    "Glen Burnie, Maryland": (39.1626, -76.6247),
    "Laurel, Maryland": (39.0993, -76.8483),
    "Gettysburg, Pennsylvania": (39.8309, -77.2311),
    "Philipsburg, Pennsylvania": (40.8962, -78.2206),
    "Baldwin, Michigan": (43.9011, -85.8517),
    "Burton, Michigan": (42.9995, -83.6163),
    "Lovejoy, Georgia": (33.4365, -84.3149),
    "Brookhaven, Georgia": (33.8651, -84.3363),
    "Tucker, Georgia": (33.8554, -84.2171),
    "Ellabell, Georgia": (32.1335, -81.4687),
    "East Meadow, New York": (40.7140, -73.5590),
    "Brooklyn, New York": (40.6782, -73.9442),
    "Bronx, New York": (40.8448, -73.8648),
    "Manhattan (SoHo/Canal St), New York": (40.7195, -74.0020),
    "Manhattan (Canal Street), New York": (40.7178, -74.0011),
    "Manhattan (26 Federal Plaza), New York": (40.7146, -74.0019),
    "Kent, New York": (41.4773, -73.7340),
    "Natchez, Mississippi": (31.5604, -91.4032),
    "New Orleans, Louisiana": (29.9511, -90.0715),
    "Baton Rouge, Louisiana": (30.4515, -91.1871),
    "Angola, Louisiana": (30.9557, -91.5968),
    "Jena, Louisiana": (31.6855, -92.1332),
    "Riviera Beach, Florida": (26.7753, -80.0581),
    "Homestead, Florida": (25.4687, -80.4776),
    "Tallahassee, Florida": (30.4383, -84.2807),
    "Nashville, Tennessee": (36.1627, -86.7816),
    "Memphis, Tennessee": (35.1495, -90.0490),
    "Huntsville, Alabama": (34.7304, -86.5861),
    "Montgomery, Alabama": (32.3792, -86.3077),
    "Foley, Alabama": (30.4066, -87.6836),
    "Omaha, Nebraska": (41.2565, -95.9345),
    "New Haven, Connecticut": (41.3083, -72.9279),
    "Providence, Rhode Island": (41.8240, -71.4128),
    "Columbus, Ohio": (39.9612, -82.9988),
    "Indianapolis, Indiana": (39.7684, -86.1581),
    "Seymour, Indiana": (38.9592, -85.8903),
    "Greenville, South Carolina": (34.8526, -82.3940),
    "Salt Lake City, Utah": (40.7608, -111.8910),
    "Woodburn, Oregon": (45.1437, -122.8557),
    "Elizabeth, New Jersey": (40.6640, -74.2107),
    "Somerville, New Jersey": (40.5740, -74.6099),
    "Colts Neck, New Jersey": (40.2918, -74.1726),
    "Estancia, New Mexico": (34.7581, -106.0544),
    "Lewisville, Texas": (33.0462, -96.9942),
    "Mount Pleasant, South Carolina": (32.7941, -79.8626),
}


def get_coords(city: Optional[str], state: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    """Get coordinates for a city/state pair.

    Accepts state as either a full name ("California") or 2-letter code ("CA").
    """
    if not city or not state:
        return None, None

    # Resolve state code to full name if needed (CITY_COORDS uses full names)
    state_full = state
    if len(state.strip()) == 2 and state.strip().upper() == state.strip():
        resolved = get_state_name(state.strip())
        if resolved:
            state_full = resolved

    city_state = f"{city}, {state_full}"
    if city_state in CITY_COORDS:
        return CITY_COORDS[city_state]

    # Try partial match
    city_clean = str(city).split(',')[0].split('(')[0].strip()
    city_state_clean = f"{city_clean}, {state_full}"
    if city_state_clean in CITY_COORDS:
        return CITY_COORDS[city_state_clean]

    # Try state match with city contains
    for key, coords in CITY_COORDS.items():
        if ',' in key:
            key_city, key_state = key.rsplit(',', 1)
            key_state = key_state.strip()
            if state_full == key_state and city_clean.lower() in key_city.lower():
                return coords

    return None, None
