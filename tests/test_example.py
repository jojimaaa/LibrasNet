import pytest

from main import main

def example_test(capsys):
    print("Hello from librasnet!")
    captured = capsys.readouterr()
    assert "Hello from librasnet!" in captured.out
