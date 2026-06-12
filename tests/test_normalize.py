from __future__ import annotations

from datetime import datetime, timezone

from scoredclub.normalize import find_match, merge_profiles, normalize_name
from scoredclub.schemas import EntityProfile, EntityType, SocialPresence
from tests.conftest import make_minimal_profile, make_top_profile


class TestNormalizeName:
    def test_about_blank(self):
        assert normalize_name("://about blank") == "about blank"

    def test_aeden(self):
        assert normalize_name("ÆDEN") == "aeden"

    def test_rso(self):
        assert normalize_name("RSO.Berlin") == "rso"

    def test_strip_club_token(self):
        assert normalize_name("Club der Visionaere") == "visionaere"
        assert normalize_name("KitKat Club") == "kitkat"

    def test_diacritics(self):
        assert normalize_name("Köpenicker Träume") == "kopenicker traume"


class TestFindMatch:
    def test_exact_id(self):
        existing = [make_top_profile()]
        incoming = EntityProfile(entity_id="testclub", name="Whatever")
        assert find_match(incoming, existing) is existing[0]

    def test_normalized_name(self):
        existing = [EntityProfile(entity_id="about-blank", name="://about blank")]
        incoming = EntityProfile(name="About Blank")
        assert find_match(incoming, existing) is existing[0]

    def test_alias(self):
        existing = [
            EntityProfile(
                entity_id="wilde-renate",
                name="Wilde Renate",
                aliases=["Salon zur Wilden Renate"],
            )
        ]
        incoming = EntityProfile(name="Salon zur wilden Renate")
        assert find_match(incoming, existing) is existing[0]

    def test_fuzzy_requires_corroboration(self):
        """Similar names without shared evidence must NOT merge."""
        existing = [EntityProfile(entity_id="oxi", name="OXI Club", district="Lichtenberg")]
        incoming = EntityProfile(name="OXI Clubs", district="Neukölln")
        assert find_match(incoming, existing) is None

    def test_fuzzy_with_shared_district(self):
        existing = [EntityProfile(entity_id="griessmuehle", name="Griessmühle", district="Neukölln")]
        incoming = EntityProfile(name="Griessmuehle ", district="Neukölln")
        assert find_match(incoming, existing) is existing[0]

    def test_no_match(self):
        existing = [make_top_profile()]
        incoming = EntityProfile(name="Völlig Anderer Club")
        assert find_match(incoming, existing) is None


class TestMerge:
    def test_newer_wins(self):
        old = make_top_profile()
        old.online.instagram.followers = 100
        new = EntityProfile(
            entity_id="testclub",
            name="Testclub",
            last_verification=datetime(2026, 6, 13, tzinfo=timezone.utc),
        )
        new.online.instagram.followers = 200
        merged = merge_profiles(old, new)
        assert merged.online.instagram.followers == 200

    def test_null_incoming_does_not_overwrite(self):
        old = make_top_profile()
        new = EntityProfile(
            entity_id="testclub",
            name="Testclub",
            last_verification=datetime(2026, 6, 13, tzinfo=timezone.utc),
        )
        merged = merge_profiles(old, new)
        assert merged.district == "Friedrichshain"
        assert merged.online.instagram.followers == 120_000

    def test_lists_unioned(self):
        old = make_minimal_profile()
        old.press.major_features = ["RA Feature"]
        new = make_minimal_profile()
        new.press.major_features = ["RA Feature", "Mixmag"]
        merged = merge_profiles(old, new)
        assert merged.press.major_features == ["RA Feature", "Mixmag"]

    def test_seed_name_kept_and_alias_added(self):
        seed = EntityProfile(entity_id="rso-berlin", name="RSO.Berlin")
        incoming = EntityProfile(
            entity_id="rso-berlin",
            name="Revier Südost",
            online={"website": SocialPresence(url="https://rso.berlin")},
        )
        merged = merge_profiles(seed, incoming)
        assert merged.name == "RSO.Berlin"
        assert "Revier Südost" in merged.aliases
        assert merged.online.website.url == "https://rso.berlin"

    def test_type_upgrade(self):
        seed = EntityProfile(entity_id="x", name="X")
        incoming = EntityProfile(
            entity_id="x",
            name="X",
            type=EntityType.series,
            last_verification=datetime(2026, 6, 13, tzinfo=timezone.utc),
        )
        merged = merge_profiles(seed, incoming)
        assert merged.type == EntityType.series
