# Appium Agent


## Getting started

To install this you can either use docker or just install all the dependencies for python and then run the code.

You will need to have install Appium using Node.js. Once you have installed it and also the drivers for Android and iOS you can start the appium server in your machine. 

If the appium server is located in a different server you will have to add `appium_url` in `agent_func.py`.

In .env you will have to change the values for the environment variables to point to the right ios/android devices and apps.

### Set up BarkoAgent

Once you have done that, you will get an agent running in a websocket configuration. Now you need to:


1. Navigate to https://beta.barkoagent.com/chat
2. Create a new project, and select the `Custom Agent`
3. You will get your unique `uuid4` for that project
4. add the `System Prompt` (we have added sample system prompt for this project in [here](system_prompt.txt))
5. Copy the `uuid4` and save the project.
6. Add you `uuid4` to the .env
7. Run your agent


### Run with docker

To run with docker, you might understand that you will need to do communication with an APPIUM server! running without docker might be simpler in this case.

First add to the .env file the value from `Agent WS URI endpoint` that you got from point 5 during BarkoAgent setup.

then in appium-agent directory run:

<pre>
    docker-compose up
</pre>

### Run with python

Make sure you are using a Py-TestUI suported version python (3.9-3.12)

<pre>
    pip install -r requirements.txt
    python client.py
</pre>

It will ask you to input the BACKEND_WS_URI from  `Agent WS URI endpoint`

## Your first prompt

You can test this custom agent by writing:

`Once you are in the app validate any element`
