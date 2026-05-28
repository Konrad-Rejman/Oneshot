# Local LM Oneshot Campaign Repo

Adaptation of my LLM-Pen-and-Paper project.

### By Konrad Rejmanowski

## Acknowledgement

This project is currently built to use the Mistral-7B-Instruct-v0.3 model, which you can find on HuggingFace at https://huggingface.co/mistralai/Mistral-7B-Instruct-v0.3.

## Setup:

### Installation:

You will need the following installed in order to run the program:

1. Python 3.12 (Version is important for compatibility with GPU Processing)

##### Pip
2. pandas
3. rouge-score
4. scikit-learn
5. spacy
6. transformers 
7. accelerate 
8. sentencepiece
9. huggingface_hub

##### Pthon -m
10. en_core_web_md (python -m spacy download en_core_web_md)
11. torch (python -m pip install torch)
12. torchvision (python -m pip install torchvision)

You can check for dependencies in the requirements.txt file.

### Additional Files / Directories:

You will need to initialise the following correctly:

- A data.csv file with the headings ',Session,User,Tokens,Playtime (s)' for data on the sessions and feedback to be collected.
- A 'sessions' folder in the root directory for session transcripts to be saved.

### Running Program:

To run the program, follow all previous instructions and (ensuring you are in the correct root directory in terminal) run the command 'python main.py' in the terminal (ensuring you have an up-to-date version of python installed). 

The program should run correctly from there, initialising the model and starting the gameplay loop. To exit the program, press ctrl + c.

If an unexpected session interrupt occurs a backup.pkl file should be saved containing the session details at time of failure. This file will ensure that the next time the code is run, it loads the saved backup data instead of starting again. 

For correct functionality delete this backup file once the data has been loaded into the new session, otherwise it will continually attempt to load from backup.
