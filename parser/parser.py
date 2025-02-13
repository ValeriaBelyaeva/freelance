def parsing(file_name="messages.txt", codec="utf-8"):
    """
    Summary:
        This function parses a given log file to extract data from specific lines containing 
        the keyword "Проект". Each parsed segment (from "Проект" until the next blank line) 
        is stored in a dictionary, and all such dictionaries are returned as a list.

    Description:
        1. Opens the specified file with the provided encoding.
        2. Reads up to the first 100 lines for demonstration.
        3. Detects the start of a new log block by searching for the word "Проект".
        4. Aggregates lines into a dictionary until an empty line is reached.
        5. Splits each line using the first colon (":") as a delimiter, treating the part
           before the colon as the key and the part after as the value.
        6. Appends each completed dictionary to a list once a blank line is encountered.

    Args:
        file_name (str): The name (and path if needed) of the log file to parse.
        codec (str): The text encoding used to read the file contents.

    Returns:
        list[dict]: A list of dictionaries, where each dictionary represents one 
        parsed block of log data. Keys are field names extracted from the log,
        and values are the corresponding data strings.
    """
    # Open the file using the specified codec
    with open(file_name, encoding=codec) as f:
        logs = []           # Will store all parsed log blocks
        parse_flag = 0      # Indicates if we are currently parsing a "project" block
        current_log = {}    # Temporary dictionary for the current block

        # Process up to 100 lines for demonstration purposes
        for line in f.readlines()[:100]:
            # If the line contains "Проект", we are at the start of a new block
            if "Проект" in line:
                parse_flag = 1
                current_log = {}

            # An empty line marks the end of the current block
            if line.strip() == "":
                parse_flag = 0
                logs.append(current_log)

            # If we are inside a "project" block, parse the line for key-value pairs
            if parse_flag == 1:
                name, data = line[:-1].split(":", 1)
                current_log[name] = data.strip()

    return logs