# Local LM Oneshot Campaign Repo

Adaptation of my LLM-Pen-and-Paper project.

### By Konrad Rejmanowski

## Setup:

### Installation:

You will need the following installed in order to run the program:

1. Python

##### Pip
2. pandas
3. dotenv
4. google-genai
5. rouge-score
6. scikit-learn
7. spacy

##### Pthon -m
8. en_core_web_md (python -m spacy download en_core_web_md)

You can check for dependencies in the requirements.txt file.

### Additional Files / Directories:

You will need to initialise the following correctly:

- A .env file with your 'APIKEY' variable declared (this is a link to google AI studios API: https://ai.google.dev/gemini-api/docs).
- A data.csv file with the headings ',Session,User,Context Method,Consistency (1-7),Rule Adherence (1-7),Creativity (1-7),Enjoyment (1-7),Tokens,Playtime (s)' for data on the sessions and feedback to be collected.
- A 'sessions' folder in the root directory for session transcripts to be saved.

### Running Program:

To run the program, follow all previous instructions and (ensuring you are in the correct root directory in terminal) run the command 'python main.py' in the terminal (ensuring you have an up-to-date version of python installed). 

The program should run correctly from there, initialising the model and starting the gameplay loop. To exit the program, press ctrl + c and input the feedback on the session.

If a failure occurs (most commonly due to the server hosting the AI having unusually high demand), a backup.pkl file should be saved containing the session details at time of failure. This file will ensure that the next time the code is run, it loads the saved backup data instead of starting again. 

For correct functionality delete this backup file once the data has been loaded into the new session, otherwise it will continually attempt to load from backup.
