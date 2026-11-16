package pkg_test

import (
    "testing"
    "example.org/fixture/lib/pkg"
)

func TestValue(t *testing.T) {
    if pkg.Value() != 7 { t.Fatal("value") }
}
