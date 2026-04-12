import wiki_system


def test_package_importable():
    assert wiki_system.__version__ == "0.1.0"
