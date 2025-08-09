import re
import sys

# --- Global State ---
# We keep these global for simplicity, but in a larger application,
# they would be part of a transpiler class.
global_env = {}
functions = {}

# --- SECURITY WARNING ---
# This transpiler uses Python's `eval()` function, which is a security risk.
# It can execute ANY arbitrary Python code. Do not run untrusted Flux code
# with this interpreter on a production system.
# A safer, but much more complex, approach would be to build a full
# Abstract Syntax Tree (AST) parser and interpreter.

def find_block_end(lines, start_index):
    """
    Finds the matching '}' for a block starting at `start_index`.
    This is CRUCIAL for correctly parsing nested structures.
    It works by counting the number of open '{' and closing '}' braces.
    """
    open_braces = 1
    # We start searching from the line after the one with the opening brace
    for i in range(start_index + 1, len(lines)):
        line = lines[i].strip()
        if '{' in line:
            open_braces += 1
        if '}' in line:
            open_braces -= 1
        if open_braces == 0:
            return i
    # If we fall through the loop, the block was never closed.
    raise SyntaxError("Unmatched '{' brace: Code block was never closed.")

def eval_expr(expr, env):
    """
    Safely evaluates an expression string in the context of an environment.
    """
    # Replace $var with len(var) for getting list lengths
    expr = re.sub(r"\$(\w+)", lambda m: f"len({m.group(1)})", expr)
    
    # IMPROVEMENT: To prevent bugs where one variable name is a substring
    # of another (e.g., 'a' and 'ab'), we sort the variables by length
    # in descending order before substitution.
    for var in sorted(env, key=len, reverse=True):
        # Using repr() is key, as it correctly formats values as Python literals
        # e.g., a string 'hi' becomes "'hi'", a list [1,2] becomes "[1, 2]"
        expr = re.sub(rf"\b{var}\b", repr(env[var]), expr)
        
    try:
        # We limit the available built-in functions for a bit more safety.
        return eval(expr, {"__builtins__": {"len": len, "print": print, "str": str, "int": int, "float": float}})
    except Exception as e:
        print(f"Runtime Error: Could not evaluate expression '{expr}'. Reason: {e}", file=sys.stderr)
        return None

def parse_single_line(line, env):
    """
    Parses and executes a single line of Flux code that is not a control structure.
    This handles assignments and print statements.
    """
    line = line.strip()
    
    # Handle print statements with comma-separated arguments
    if line.startswith("print("):
        content = line[6:-1]
        if content: # Handle empty print()
            parts = content.split(',')
            evaluated_parts = [eval_expr(p.strip(), env) for p in parts]
            print(*evaluated_parts)
        else:
            print() # print() with no arguments prints a newline

    # Handle variable and list assignments
    elif "=" in line and not line.startswith("fn"):
        var, val = line.split("=", 1)
        var = var.strip()
        val = val.strip()
        
        # List assignment: e.g., a = {1, "hello", 3}
        if val.startswith("{") and val.endswith("}"):
            list_items = val[1:-1].split(",")
            # We evaluate each item to get its proper type (number, string, etc.)
            env[var] = [eval_expr(v.strip(), env) for v in list_items if v.strip()]
        # Simple variable assignment: e.g., x = y + 5 or n = numbers[i]
        else:
            env[var] = eval_expr(val, env)

    # Handle standalone function calls that don't assign to a variable
    elif re.match(r"^\w+\(.*\)$", line):
        match = re.match(r"(\w+)\((.*?)\)", line)
        if match:
            # For now, we assume this is a user-defined function.
            # Built-in function calls should be inside expressions.
            name, args_str = match.groups()
            args = []
            if args_str:
                args = [eval_expr(arg.strip(), env) for arg in args_str.split(",")]
            call_function(name, args, env) # We don't care about the return value here

def define_function(name, params, body):
    """Stores a function definition."""
    functions[name] = {"params": params, "body": body}

def call_function(name, args, outer_env):
    """Executes a function."""
    if name not in functions:
        raise NameError(f"Function '{name}' is not defined.")
    
    func_def = functions[name]
    if len(args) != len(func_def["params"]):
        raise TypeError(f"Function '{name}' expected {len(func_def['params'])} arguments, but got {len(args)}.")
    
    # Create a local environment for the function call
    local_env = outer_env.copy()
    for param_name, arg_value in zip(func_def["params"], args):
        local_env[param_name] = arg_value
        
    # Functions can have return values
    return_val = execute(func_def["body"], local_env)
    return return_val

def execute(lines, env):
    """
    The main execution engine. Recursively executes a block of Flux code.
    This is the core of the new, robust interpreter.
    """
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # --- FEATURE: Skip empty lines and comments ---
        if not line or line.startswith("//"):
            i += 1
            continue

        # Handle return statements (only valid inside functions)
        if line.startswith("return("):
            expr = line[7:-1]
            return eval_expr(expr, env)
            
        # Handle 'ifthen-else' blocks
        if line.startswith("ifthen"):
            condition = re.search(r"\((.*?)\)", line).group(1)
            if_block_start = i
            if_block_end = find_block_end(lines, if_block_start)
            if_block = [l.strip() for l in lines[if_block_start + 1 : if_block_end]]
            
            else_block = []
            i = if_block_end # Move instruction pointer past the 'if' block
            # Check if an 'else' block immediately follows
            if i + 1 < len(lines) and lines[i + 1].strip().startswith("else"):
                else_block_start = i + 1
                else_block_end = find_block_end(lines, else_block_start)
                else_block = [l.strip() for l in lines[else_block_start + 1 : else_block_end]]
                i = else_block_end # Move pointer past the 'else' block

            if eval_expr(condition, env):
                execute(if_block, env) # Recursive call for the block
            else:
                execute(else_block, env) # Recursive call for the block

        # Handle 'while' blocks
        elif line.startswith("while"):
            condition = re.search(r"\((.*?)\)", line).group(1)
            block_start = i
            block_end = find_block_end(lines, block_start)
            block = [l.strip() for l in lines[block_start + 1 : block_end]]
            i = block_end # Move instruction pointer past the block definition
            
            while eval_expr(condition, env):
                execute(block, env) # Recursive call for the block

        # Handle single-line statements
        else:
            parse_single_line(line, env)
        
        i += 1
    # If a function doesn't explicitly return, it returns None by default
    return None

def run_flux(code):
    """
    The main entry point to run a Flux program.
    """
    global global_env, functions
    global_env = {}
    functions = {}

    lines = code.strip().split("\n")
    
    # First pass: Hoist all top-level function definitions
    i = 0
    clean_lines = []
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("fn"):
            name = re.match(r"fn (\w+)", line).group(1)
            params_str = re.search(r"\((.*?)\)", line).group(1)
            params = [p.strip() for p in params_str.split(",") if p]
            
            block_start = i
            block_end = find_block_end(lines, block_start)
            body = [l.strip() for l in lines[block_start + 1 : block_end]]
            define_function(name, params, body)
            i = block_end + 1 # Skip past the entire function definition
        else:
            clean_lines.append(lines[i])
            i += 1

    # Second pass: Execute the main body of the code
    execute(clean_lines, global_env)
    
flux_code = """
// Flux Prime Number and FizzBuzz Demonstrator

// A function to check if a number is prime
fn isPrime(n) {
    ifthen (n <= 1) {
        return(0) // 0 and 1 are not prime
    }
    j = 2
    while (j * j <= n) {
        ifthen (n % j == 0) {
            return(0) // It's divisible, so not prime
        }
        j = j + 1
    }
    return(1) // It's prime
}

// Main program execution starts here
print("--- Prime Number Checks ---")
testNumbers = {7, 10, 13, 1}
i = 0
while (i < $testNumbers) {
    num = testNumbers[i]
    result = isPrime(num)
    ifthen (result == 1) {
        print(num, "is prime.")
    } else {
        print(num, "is NOT prime.")
    }
    i = i + 1
}

print("") // Print a blank line
print("--- Nested Logic: FizzBuzz Style ---")
// This demonstrates nested control flow, which the old parser could not handle.
i = 1
while (i <= 15) {
    // Outer 'if'
    ifthen (i % 3 == 0) {
        // Nested 'if'
        ifthen (i % 5 == 0) {
            print("FizzBuzz")
        } else {
            print("Fizz")
        }
    } else {
        ifthen (i % 5 == 0) {
            print("Buzz")
        } else {
            print(i)
        }
    }
    i = i + 1
}
"""

# Run the transpiler with the advanced script
run_flux(flux_code)

