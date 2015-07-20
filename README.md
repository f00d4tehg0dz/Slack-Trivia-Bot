# Slack-Trivia-Bot
Slack Trivia Bot is a trivia based bot for the Slack API
***lightly based off of https://github.com/ph7vc/regis-philbot***

_raw_questions.zip is the unmodified questions.sql

questions_sql_dump.zip is a dump from our sql database. [can be used for reference] 

**Pre-req:**

* MySQL (or similar sql)
* PHP 5.1+ (phpmyadmin is nice, but not required)
* Python

**Instructions:**

- Simply run create_schema.sql to build your sql database.
- Make sure your incoming and outgoingtoken from the slack api and incoming hook are registered from slack and insert them inside conf/settings.ini
- Import the questions.sql 
  -  Either from raw_questions.zip or questions.sql_dump.zip (depending on your sql knowledge)
- Run trivia_bot_background.sh
