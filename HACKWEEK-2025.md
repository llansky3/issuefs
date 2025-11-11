# Hackweek 2025 project

issuefs: FUSE filesystem representing issues (e.g. JIRA) for the use with AI agents code-assistants

## Background
Creating a FUSE filesystem (issuefs) that mounts issues from various ticketing systems (Github, Jira, Bugzilla, Redmine) as files to your local file system.

And why this is good idea?

* User can use favorite command line tools to view and search the tickets
* User can just use AI agentic capabilities from your favorite IDE to ask question about the issue, project or functionality while providing relavant tickets as context without extra work. 
* User can use it during development of the new features when youlet the AI agent to jump start the solution based on the relevant. The issuefs will give the AI agent the context (AI agents just read few more files). No need for copying and pasting issues to user prompt or by using extra MCP tools to access the issues. These you can still do but this approach is on purpose different.

<img src="docs/Gemini_Generated_Image_Workflow_Overview.png">

## User scenario #1
* User is tasked to implement feature A in a ticket JIRA ABC-1234. This is also related to some BZ and also some upstream Github issues.
* User sets up issuefs in a sub-folder with the right queries/settings so relevant tickets are represented as text files in your file system.
* User uses VS code to read and search the tickets to understand the problem
* User uses his favorite AI co-pilot to jump start and get ideas for the solution. The relavant tickets are just files and the agent will use them as context when developing solution. User doesn't need additional setup or copying from tickets to provide AI agent/LLM relevant information.

## Resources

There is a prototype implementation [here](https://github.com/llansky3/issuefs).
This currently sort of works with JIRA only.

## Goals
1. Add Github issue support 
2. Proof the concept by apply the approach on itself using Github issues for tracking and development of new features
3. Add support for Bugzilla and Redmine using this approach in the process of doing it. Recored a video of it.
4. Clean-up and test the implementation and create some documentation
5. (stretch goal) Create a blog post about this
 