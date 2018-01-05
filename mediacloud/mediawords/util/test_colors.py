from mediawords.test.test_database import TestDatabaseWithSchemaTestCase
from mediawords.util.colors import *


def test_hex_to_rgb():
    assert hex_to_rgb('ff0000') == (255, 0, 0,)
    assert hex_to_rgb('FFFFFF') == (255, 255, 255,)
    assert hex_to_rgb('#ff0000') == (255, 0, 0,)
    assert hex_to_rgb('#FFFFFF') == (255, 255, 255,)


def test_rgb_to_hex():
    assert rgb_to_hex(255, 0, 0).lower() == 'ff0000'
    assert rgb_to_hex(0, 0, 0).lower() == '000000'
    assert rgb_to_hex(255, 255, 255).lower() == 'ffffff'


def test_analogous_color():
    starting_color = '0000ff'
    colors = analogous_color(color=starting_color, my_slices=255, slices=255)
    assert len(colors) == 256
    assert colors[0].lower() == starting_color
    assert colors[1].lower() == '0400ff'
    assert colors[-2].lower() == '0008ff'
    assert colors[-1].lower() == starting_color


class TestGetConsistentColorTestCase(TestDatabaseWithSchemaTestCase):

    def test_get_consistent_color(self):
        partisan_colors = {
            'partisan_2012_conservative': 'c10032',
            'partisan_2012_liberal': '00519b',
            'partisan_2012_libertarian': '009543',
        }

        for color_id, color in partisan_colors.items():
            got_color = get_consistent_color(db=self.db(), item_set='partisan_code', item_id=color_id)
            assert got_color == color

        color_c_baz = get_consistent_color(db=self.db(), item_set='c', item_id='baz')
        color_b_baz = get_consistent_color(db=self.db(), item_set='b', item_id='baz')
        color_b_bar = get_consistent_color(db=self.db(), item_set='b', item_id='bar')
        color_a_baz = get_consistent_color(db=self.db(), item_set='a', item_id='baz')
        color_a_bar = get_consistent_color(db=self.db(), item_set='a', item_id='bar')
        color_a_foo = get_consistent_color(db=self.db(), item_set='a', item_id='foo')

        num_db_colors = self.db().query("SELECT COUNT(*) FROM color_sets").flat()
        assert num_db_colors[0] == 9

        assert color_a_foo != color_a_bar
        assert color_a_foo != color_a_baz
        assert color_a_bar != color_a_baz
        assert color_b_bar != color_b_baz

        color_a_foo_2 = get_consistent_color(db=self.db(), item_set='a', item_id='foo')
        color_a_bar_2 = get_consistent_color(db=self.db(), item_set='a', item_id='bar')
        color_a_baz_2 = get_consistent_color(db=self.db(), item_set='a', item_id='baz')
        color_b_bar_2 = get_consistent_color(db=self.db(), item_set='b', item_id='bar')
        color_b_baz_2 = get_consistent_color(db=self.db(), item_set='b', item_id='baz')
        color_c_baz_2 = get_consistent_color(db=self.db(), item_set='c', item_id='baz')

        assert color_a_foo_2 == color_a_foo
        assert color_a_bar_2 == color_a_bar
        assert color_a_baz_2 == color_a_baz
        assert color_b_bar_2 == color_b_bar
        assert color_b_baz_2 == color_b_baz
        assert color_c_baz_2 == color_c_baz

    def test_consistent_colors_create(self):
        item_set = 'test_set'
        unique_color_mapping = dict()

        # Test if helper is able to create new colors when it runs out of hardcoded set
        for x in range(50):
            item_id = 'color-%d' % x
            color = get_consistent_color(db=self.db(), item_set=item_set, item_id=item_id)
            assert len(color) == len('ffffff')
            unique_color_mapping[item_id] = color

        # Make sure that if we run it again, we'll get the same colors
        for x in range(50):
            item_id = 'color-%d' % x
            color = get_consistent_color(db=self.db(), item_set=item_set, item_id=item_id)
            assert len(color) == len('ffffff')
            assert unique_color_mapping[item_id] == color
