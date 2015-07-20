#!/usr/bin/python

# TODO:
# If a sufficiently high run was ended (by an unanswered question or someone else getting it right), send a message about it.
# When a player is first added to the players table, send a message welcoming the new player.
# Modify the scoring to reset on month/week/day change (as configured?).
# Allow an array of answers so that common misspellings will work too (and alternate answers like "one" and "1").
# Run through the pre-loaded questions to fix spelling and grammar, remove or correct the incorrect questions (there are some that aren't part of that pure garbage batch that are still messed up some) and to make sure they are full sentences/questions.
# Implement the "load" command.

import logging
import logging.config
import ConfigParser
import mysql.connector
from subprocess import Popen, PIPE
import zipfile
import os
import BaseHTTPServer
import urlparse
import requests
import random
import threading
import json
#import sys
#import time
#import math

bot = None
Config = None
httpd = None
outgoingToken = ""
incomingHookURL = ""
dbConfigMap = {}

expectedRequestKeys = ['user_id','channel_name','timestamp','team_id','channel_id','token','text','service_id','team_domain','user_name']

def main():
    loadConfig()
    sendMessage("Trivia bot initalizing...")
    #Check if the tables are already created and create them if they aren't.
    createSchema()
    
    global httpd
    httpd = BaseHTTPServer.HTTPServer(('', 8150), RequestHandler)
    httpd.socket.settimeout(1)
    sendMessage("Trivia bot initalized.")
    
    # Just listen for requests to start, stop or do other things.
    # Starting the bot will create a new bot instance that will run and handle posting to the channel in between user input.
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    
    if bot is not None:
        bot.stop()
    httpd.server_close()
    sendMessage("Trivia bot shut down.")

def loadConfig():
    #print("Current working directory: " + os.getcwd())
    #Loading the logging configuration file.
    logging.config.fileConfig('logging.conf')
    logging.info("Starting trivia bot.")
    
    # Open the bot configuration file.
    global Config
    Config = ConfigParser.ConfigParser()
    Config.read("conf/settings.ini")
    
    global outgoingToken
    outgoingToken = Config.get("SlackIntegration", "outgoingToken")
    global incomingHookURL
    incomingHookURL = Config.get("SlackIntegration", "incomingHookURL")
    
    global dbConfigMap
    dbConfigMap = {
        'user': Config.get("Database", "user"),
        'password': Config.get("Database", "password"),
        'host': Config.get("Database", "host"),
        'database': Config.get("Database", "database"),
        'raise_on_warnings': Config.getboolean("Database", "raise_on_warnings"),
    }
    
    socket = Config.get("Database", "unix_socket")
    if socket is not None and socket != "":
        dbConfigMap["unix_socket"] = socket

def createSchema():
    # For this to work, the database has to already be created and the user has to have been created with full rights on that database.
    # "CREATE DATABASE `trivia`;"
    # "GRANT ALL PRIVILEGES ON trivia.* To 'trivia'@'localhost' IDENTIFIED BY 'restricted';"
    cnx = mysql.connector.connect(**dbConfigMap)
    cursor = cnx.cursor()
    
    logging.debug("Checking for the 'questions' table as a way to see if the tables/schema already exists")
    # Assume that if the "questions" table is there, that the whole schema is there (and that if the "questions" table is not there, that none of the schema is).
    cursor.execute("SHOW TABLES LIKE 'questions'")
    result = cursor.fetchone()
    
    if result:
        # The schema exists.
        logging.debug("The 'questions' table exists; assuming the whole schema exists")
        cursor.close()
        cnx.close()
        return
    
    #else, the schema does not exist. Run the script to create it.
    cursor.close()
    cnx.close()
    logging.info("The 'questions' table did not exist; assuming the whole schema is missing. Running schema creation script.")
    
    parameters = ['mysql', '-u', dbConfigMap["user"], "-p" + dbConfigMap["password"]]
    if "unix_socket" in dbConfigMap and dbConfigMap["unix_socket"] != "":
        parameters.append("-S")
        parameters.append(dbConfigMap["unix_socket"])
    parameters.append(dbConfigMap["database"])
    
    process = Popen(parameters, stdout=PIPE, stdin=PIPE)
    output = process.communicate('source create_schema.sql')[0]
    logging.debug("Output of creating the schema: " + output)
    
    # Load the default questions.
    logging.info("Loading the default questions.")
    with zipfile.ZipFile('questions.zip', "r") as z:
        z.extractall("")
    process = Popen(parameters, stdout=PIPE, stdin=PIPE)
    output = process.communicate('source questions.sql')[0]
    logging.debug("Output of loading the questions: " + output)
    # Clean up the extracted file.
    os.remove("questions.sql")
    
    logging.info("Schema created and default questions loaded")

def processCommand(msg, userId):
    logging.info("Received command: " + msg)
    # Split the command into the various parameters.
    parameters = msg.split()
    
    if parameters[0] == "start":
        global bot
        if bot is None:
            # Create the bot instance.
            bot = Trivia()
            bot.start()
        else:
            sendMessage("A trivia game is already running.")
    elif parameters[0] == "load":
        sendMessage("Not implemented yet. Be patient (very patient).")
        #loadQuestionsFile(parameters[1])
    elif parameters[0] == "help":
        # Send the help text to the channel.
        helpText = "The options available are...\n"
        helpText += " * !trivia start - Starts the trivia game.\n"
        helpText += " * !trivia stop - Stops the trivia game.\n"
        helpText += " * !trivia delay <n> - Sets the time between hints and questions, in seconds.\n"
        helpText += " * !trivia scores - Shows the top 3 high scorers.\n"
        helpText += " * !trivia runs - Shows the top 3 best runs.\n"
        helpText += " * !trivia answers - Shows the top 3 players by questions answered.\n"
        helpText += " * !trivia me - Shows details on your own scoring.\n"
        helpText += " * !trivia questions - Displays how many questions are loaded.\n"
        helpText += " * !trivia load <filename> - Loads the set of questions in the given file on the server.\n"
        
        sendMessage(helpText)
    elif bot is None:
        sendMessage("Either your command was not valid, or the trivia game is not running but needs to be to process your command.")
    elif bot is not None:
        if parameters[0] == "stop":
            bot.stop()
        elif parameters[0] == "delay":
            if len(parameters) < 2 or parameters[1] == "" or not parameters[1].isdigit():
                sendMessage('The "number of seconds" delay parameter is invalid.')
            
            bot.setDelay(parameters[1])
        elif parameters[0] == "scores":
            bot.showHighScores()
        elif parameters[0] == "runs":
            bot.showHighRuns()
        elif parameters[0] == "answers":
            bot.showHighQuestions()
        elif parameters[0] == "me":
            bot.showPlayersDetails(userId)
        elif parameters[0] == "questions":
            bot.showQuestionCount()

def sendMessage(msg):
    response = requests.post(incomingHookURL, data='{"text":' + json.dumps(msg) + '}')
    
    if not(str(response) == "<Response [200]>"):
        logging.error("Send message failed. Message: " + msg)
        logging.debug("The error response from the server was: " + response.text)

class RequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return
    
    def do_GET( self ):
        self.send_response(418)
        self.end_headers()
    
    def do_POST( self ):
        self.send_response(200)
        self.end_headers()
        
        request_len = int(self.headers['Content-Length'])
        request = self.rfile.read(request_len)
        
        post = urlparse.parse_qs(request)
        logging.debug("Post: " + str(post))
        
        if not(set(expectedRequestKeys).issubset(post.keys())):
            return
        
        if not( post["token"][0] == outgoingToken ):
            logging.info("Received a request with an invalid Slack outgoing token.")
            return
        elif ( post["user_name"][0] == 'slackbot' ):
            return
        
        message = post["text"][0]
        if message[:8] == "!trivia ":
            processCommand(message[8:], post["user_id"][0])
        else:
            if bot is not None:
                isCorrect = bot.checkAnswer(message)
                if isCorrect:
                    bot.stopTimer()
                    bot.scorePlayer(post["user_id"][0], post["user_name"][0])
                    bot.clearQuestion()
                    bot.startTimer()

class Trivia():
    def __init__(self):
        self.question = {}
        self.lastAnsweredBy = ""
        self.unansweredQuestions = 0
        self.botTimer = None
        self.delay = Config.getint("Config", "defaultDelay")
        self.unansweredStop = Config.getint("Config", "unansweredStop")
        
        logging.info("Bot initialized with Delay: " + str(self.delay) + "; unansweredStop: " + str(self.unansweredStop))
    
    def start(self):
        # Clear any runs, in case the game was not stopped properly last time.
        self.clearRuns()
        self.loop()
        logging.debug("Started Trivia bot.")
    
    def stop(self):
        sendMessage("Stopping the trivia game.")
        
        self.stopTimer()
        self.clearRuns()
        
        global bot
        bot = None
    
    def stopTimer(self):
        if self.botTimer is not None:
            self.botTimer.cancel()
            self.botTimer = None
    
    def startTimer(self):
        self.botTimer = threading.Timer(bot.delay, self.loop)
        self.botTimer.start()
    
    def resetTimer(self):
        self.stopTimer()
        self.startTimer()
    
    def setDelay(self, newDelay):
        self.delay = int(newDelay)
        
    def loop(self):
        if not self.question or not "id" in self.question or self.question["id"] == "":
            self.nextQuestion()
        else:
            if self.question["hintLevel"] == 0:
                hint = "First hint: "
                # Show the first hint, the first character of each word.
                words = self.question["answer"].split()
                
                for word in words:
                    first = True
                    
                    for letter in word:
                        if first:
                            hint += letter
                            first = False
                        else:
                            hint += "-"
                    hint += " "
                sendMessage(hint)
                self.question["hintLevel"] += 1
            elif self.question["hintLevel"] == 1:
                hint = "Second hint: "
                # Show the second hint, the first three letters (does not include hint one, in order to keep some more challenge still on short answers).
                letterCnt = 0
                
                for letter in self.question["answer"]:
                    if letterCnt < 3 or letter == " ":
                        hint += letter
                    else:
                        hint += "-"
                    letterCnt += 1
                sendMessage(hint)
                self.question["hintLevel"] += 1
            elif self.question["hintLevel"] == 2:
                hint = "Third hint: "
                # Show the third hint, all of the vowels (does not include the previous hints, in order to keep some more challenge still on short answers).
                
                for letter in self.question["answer"].lower():
                    if "aeiou ".find(letter) != -1:
                        hint += letter
                    else:
                        hint += "-"
                sendMessage(hint)
                self.question["hintLevel"] += 1
            else:
                # No more hints. Give the answer.
                sendMessage("Time's up! No one guessed the answer.\nAnswer: " + self.question["answer"])
                self.clearQuestion()
                self.clearRuns()
                self.unansweredQuestions += 1
                
                if self.unansweredQuestions >= self.unansweredStop:
                    sendMessage("Nobody has answered the last " + str(self.unansweredQuestions) + " questions! It appears no-one is playing (I *hope* no-one is playing).")
                    bot.stop()
                    return
        
        # Run until stopped via inactivity or the stop command.
        # If a question is answered correctly, this timer will be stopped and recreated so that there is always a consistent delay/break between an answer and the next question.
        self.startTimer()
    
    def clearQuestion(self):
        self.question = {}
    
    def nextQuestion(self):
        # Pick a random question from the database and load it into memory.
        # This isn't truly random, as gaps will skew the results to the questions after the gaps, but solving that problem probably isn't worth it for this use.
        # The count of the number of times a question is asked is being tracked to help determine how much of a problem that is.
        # More information on the various ways to select a random row can be found here: http://jan.kneschke.de/projects/mysql/order-by-rand/
        randomQuery = "SELECT q.id, q.question, q.answer FROM questions AS q JOIN (SELECT (RAND() * (SELECT MAX(id) FROM questions)) AS id) AS r WHERE q.id >= r.id ORDER BY q.id ASC LIMIT 1"
        
        cnx = mysql.connector.connect(**dbConfigMap)
        cursor = cnx.cursor()
        cursor.execute(randomQuery)
        result = cursor.fetchone()
        
        if result is None:
            # Uh oh. A random question could not be grabbed. Something is very wrong with the data. Fail.
            cursor.close()
            cnx.close()
            logging.error("A random question could not be grabbed.")
            raise LookupError("A random question could not be found.")
        
        self.question["id"] = result[0]
        self.question["text"] = result[1]
        self.question["answer"] = result[2]
        self.question["hintLevel"] = 0
        
        #Track that this particular question was asked so that the data can later be analyzed to see if the questions aren't random enough.
        updateCountQuery = "UPDATE questions SET asked_count = asked_count + 1"
        cursor.execute(updateCountQuery)
        cnx.commit()
        
        cursor.close()
        cnx.close()
        
        sendMessage("Question " + str(self.question["id"]) + ": " + self.question["text"])
    
    def checkAnswer(self, message):
        # Make sure a question is actually being asked.
        if self.question and "answer" in self.question:
            #TODO: Make this a little more robust in the future, like removing punctuation and excessive spaces from both sides.
            if message.lower() == self.question["answer"].lower():
                return True
        
        return False
    
    def scorePlayer(self, userId, name):
        logging.debug("Scoring player. userId: " + userId + "; name: " + name)
        self.unansweredQuestions = 0
        points = 50 - (10 * self.question["hintLevel"])
        
        cnx = mysql.connector.connect(**dbConfigMap)
        cursor = cnx.cursor()
        
        query = "SELECT * FROM players WHERE slack_id = %s"
        cursor.execute(query, (userId,))
        result = cursor.fetchone()
        
        if self.lastAnsweredBy != userId:
            # Clear the run of the previous person to answer (there should be no runs right now except for the person who just answered, which isn't in the database yet).
            # This has to be done after fetching the data from the database (since it will be cleared by this), but before committing the new data (otherwise the new data
            # would be cleared too).
            self.clearRuns()
            self.lastAnsweredBy = userId
        
        if result is None:
            # This is the first time the user has answered a question (correctly). Insert their information.
            query = "INSERT INTO players (slack_id, name, current_score, high_score, current_run, best_run, questions_answered, score_period) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
            cursor.execute(query, (userId, name, points, points, 1, 1, 1, 0))
        else:
            # Update the existing user's informtion.
            query = "UPDATE players SET current_score = %s, questions_answered = %s, current_run = %s"
            newScore = int(result[3]) + points
            newAnswerCount = int(result[7]) + 1
            newRun = int(result[5]) + 1
            queryData = [newScore, newAnswerCount, newRun]
            
            if result[2] != name:
                query += ", name = %s"
                queryData.append(name)
            if newScore > result[4]:
                query += ", high_score = %s"
                queryData.append(newScore)
            if newRun > result[6]:
                query += ", best_run = %s"
                queryData.append(newRun)
            
            query += " where slack_id = %s"
            queryData.append(userId)
            cursor.execute(query, tuple(queryData))
        
        cnx.commit()
        cursor.close()
        cnx.close()
        
        sendMessage(name + " answered correctly and earned " + str(points) + " points!")
    
    def clearRuns(self):
        cnx = mysql.connector.connect(**dbConfigMap)
        cursor = cnx.cursor()
        
        query = "UPDATE players SET current_run = 0 WHERE current_run != 0"
        cursor.execute(query)
        cnx.commit()
        
        cursor.close()
        cnx.close()
    
    def showHighScores(self):
        cnx = mysql.connector.connect(**dbConfigMap)
        cursor = cnx.cursor()
        
        query = "SELECT name, current_score FROM players ORDER BY current_score DESC LIMIT 3"
        cursor.execute(query)
        
        msg = "The top 3 scores of this period are:"
        for result in cursor.fetchall():
            msg += "\n" + result[0] + " - " + str(result[1])
        
        query = "SELECT name, high_score FROM players ORDER BY high_score DESC LIMIT 3"
        cursor.execute(query)
        
        msg += "\nThe top 3 scores of all time are:"
        for result in cursor.fetchall():
            msg += "\n" + result[0] + " - " + str(result[1])
        
        cursor.close()
        cnx.close()
        
        sendMessage(msg)
    
    def showHighRuns(self):
        cnx = mysql.connector.connect(**dbConfigMap)
        cursor = cnx.cursor()
        
        query = "SELECT name, best_run FROM players ORDER BY best_run DESC LIMIT 3"
        cursor.execute(query)
        
        msg = "The top 3 runs (questions answered in a row before another player) of all time are:"
        for result in cursor.fetchall():
            msg += "\n" + result[0] + " - " + str(result[1])
        
        cursor.close()
        cnx.close()
        
        sendMessage(msg)
    
    def showHighQuestions(self):
        cnx = mysql.connector.connect(**dbConfigMap)
        cursor = cnx.cursor()
        
        query = "SELECT name, questions_answered FROM players ORDER BY questions_answered DESC LIMIT 3"
        cursor.execute(query)
        
        msg = "The top 3 number of questions answered of all time are:"
        for result in cursor.fetchall():
            msg += "\n" + result[0] + " - " + str(result[1])
        
        cursor.close()
        cnx.close()
        
        sendMessage(msg)
    
    def showPlayersDetails(self, userId):
        cnx = mysql.connector.connect(**dbConfigMap)
        cursor = cnx.cursor()
        
        query = "SELECT * FROM players WHERE slack_id = %s"
        cursor.execute(query, (userId,))
        result = cursor.fetchone()
        
        msg = "Here are the stats on player " + result[2] + ":"
        msg += "\nCurrent Score: " + str(result[3])
        msg += "\nHigh Score: " + str(result[4])
        msg += "\nQuestions Answered: " + str(result[7])
        msg += "\nCurrent Run: " + str(result[5])
        msg += "\nBest Run: " + str(result[6])
        
        cursor.close()
        cnx.close()
        
        sendMessage(msg)
    
    def showQuestionCount(self):
        cnx = mysql.connector.connect(**dbConfigMap)
        cursor = cnx.cursor()
        
        query = "SELECT count(*) FROM questions"
        cursor.execute(query)
        result = cursor.fetchone()
        
        msg = "Total number of questions in the database: " + str(result[0])
        
        cursor.close()
        cnx.close()
        
        sendMessage(msg)

# Startup function
if __name__ == '__main__':
    main()
