"""Road paths for maps: stored once per site pair, read in either direction."""

from freight.roads import decode, encode, road, roads


def test_polylines_round_trip_exactly():
    line = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"  # the format's reference example
    assert decode(line) == [(3850000, -12020000), (4070000, -12095000), (4325200, -12645300)]
    assert encode(decode(line)) == line


def test_a_road_reads_the_same_both_ways():
    there = road("riyadh", "dammam_port")
    back = road("dammam_port", "riyadh")
    assert there and back
    assert decode(back) == decode(there)[::-1]


def test_only_known_pairs_get_a_road():
    found = roads({("riyadh", "jeddah_port"), ("riyadh", "riyadh"), ("riyadh", "atlantis")})
    assert list(found) == ["riyadh|jeddah_port"]
