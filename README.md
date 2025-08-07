# Support Ticket
This project implements a LangGraph api for a support ticket agent, utilizing a pgvector database for vector storage and retrieval. The application runs in Docker containers, exposing a secure API at http://127.0.0.1:2024 and integrating with LangSmith for the Studio UI.


## Project Structure

```
graph/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env
├── src/
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── graph.py
│   │   ├── (other Python files)
├── main.py  # or other entry point
├── (other files, e.g., dataset directory)
```

- **`src/agent`**: Contains the `agent` package with the LangGraph definition (`graph.py`).
- **Dockerfile**: Builds the Python 3.13.5 environment with dependencies.
- **docker-compose.yml**: Configures `langgraph` and `pgvector` services.
- **.env**: Stores environment variables for LangSmith and Google API.
- **requirements.txt**: Lists Python dependencies.

## Prerequisites

- **Docker**: Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) for Windows, Mac, or Linux.
- **Python 3.13.5** (optional, for local development): Install via [python.org](https://www.python.org/downloads/release/python-3135/).
- **Git**: To clone the repository.
- **PowerShell** or **Command Prompt** (Windows) or **Terminal** (Mac/Linux) for running commands.
- A valid **LangSmith project** and **Google API key** for embeddings.


## Setup Instructions

### 1. Clone the Repository

Clone the project to your local machine:

```bash
git clone https://github.com/ahsannaem/support_ticket.git
cd support_ticket
```

### 2. Configure Environment Variables

Create a `.env` file in the project root (`graph/`) with the following:

```plaintext
PYTHONPATH=./src
LANGSMITH_PROJECT=support_ticket_agent
GOOGLE_API_KEY=<your-google-api-key>
POSTGRES_CONNECTION_STRING=<your-postgres-vector-db-connection-string>
```

- Replace `<your-google-api-key>` with your Google API key for embeddings.
- Ensure `LANGSMITH_PROJECT` matches your LangSmith project name.
- Replace `<your-postgres-vector-db-connection-string>` with your PGvector connection string.

### 3. Verify Project Files

Ensure the following files are present:
- Dockerfile
- Docker-compose.yaml
- .env
- requirements.txt

### 4. Build and Run the Application

Build and start the Docker containers:

```bash
docker-compose up --build
```

### 5. Access the Application

- **API**: `http://127.0.0.1:2024`
### 6. Stop the Application

Stop the containers:
```bash
docker-compose down
```

Reset the database (if needed):
```bash
docker-compose down -v
```
Note: You might get into port configration issues because of ports already bound to some serivce so you'll have to take care of that.
## Local Development (Optional)

To run locally without Docker:

1. Activate virtual environment:
   ```bash
   python -m venv env
   source env/Scripts/activate  
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
  Note: You can skip step 3 and 4 if you already have some instance of postgres vector database already running.
3. Spin up PGvector container
  ```bash
    docker run --name pgvector-container -e POSTGRES_USER=langchain -e POSTGRES_PASSWORD=langchain -e POSTGRES_DB=langchain -p 6024:5432 -d pgvector/pgvector:pg16
  ```
4. Add database connection string to env file
  ```bash
  POSTGRES_CONNECTION_STRING = postgresql+psycopg://langchain:langchain@localhost:6024/langchain
  ```

5. Run the server:
   ```bash
   langgraph dev --allow-blocking
   ```

6. Access the API and Studio UI as above.
## Design Desicions
1. Used Async programming for better efficiency although this repo has some third party blocking apis thererfore we have to allow blocking code in dev server which is very bad for speed and efficiency.
2. Use of pyadantic models and llm wrappers for getting structured output from llms.
3. Modular code and robust error handling.
4. Used shared state graph so that all the nodes are bound to read and write from single shared state and data remain condensed.
5. Intead of using multiple RAG nodes (one for each catagory ) I used filtered quires for filtering retrival docs based on catagory.
6. Before extracting data from vector store i refreshed all the data inside of it so that the llm remain grounded in latest data. (Although this presents a computation overhead but our dataset in this case is very small so it doesn't matter much.)
7. Because of small size of document instances in the dataset I have skipped splitting and merging of documents.

## Contributing

Pull requests are welcome. For major changes, please open an issue first
to discuss what you would like to change.

Please make sure to update tests as appropriate.
