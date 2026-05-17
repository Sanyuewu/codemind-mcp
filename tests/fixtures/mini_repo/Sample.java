// A simple greeter class
public class Sample {

    private String name;

    // Constructor
    public Sample(String name) {
        this.name = name;
    }

    // Greet the stored name
    public String greet() {
        return "Hello, " + this.name + "!";
    }
}
