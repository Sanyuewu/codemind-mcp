package main

import "fmt"

// Hello returns a greeting.
func Hello(name string) string {
	return fmt.Sprintf("Hello, %s!", name)
}

// Goodbye returns a farewell.
func Goodbye(name string) string {
	return fmt.Sprintf("Goodbye, %s!", name)
}

// Greeter is a struct that greets with a prefix.
type Greeter struct {
	Prefix string
}

// Greet returns a greeting from the Greeter.
func (g Greeter) Greet(name string) string {
	return fmt.Sprintf("%s, %s!", g.Prefix, name)
}
