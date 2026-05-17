// A simple greeter function
export function greet(name: string): string {
    return `Hello, ${name}!`;
}

// A class-based greeter
export class Greeter {
    private prefix: string;

    constructor(prefix: string) {
        this.prefix = prefix;
    }

    hello(name: string): string {
        return `${this.prefix}, ${name}!`;
    }
}
