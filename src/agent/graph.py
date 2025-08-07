import asyncio
import datetime
import os

import pandas as pd
from dotenv import load_dotenv
from langchain.prompts import PromptTemplate
from langchain.schema import Document
from langchain_core.runnables import RunnableLambda
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_postgres.vectorstores import PGVector
from langgraph.graph import StateGraph, START

from agent.prompts import (
    CLASSIFICATION_PROMPT,
    DRAFT_RESPONSE_PROMPT,
    REVIEW_DRAFT_PROMPT
)
from agent.state import State
from agent.schemas import Classification, ReviewResult, Input, Output
from agent.common import make_pgvector_retriever, POSTGRES_CONNECTION_STRING
from agent.utils import refresh_rag, get_llm

# === Load environment variables ===
load_dotenv()

if not POSTGRES_CONNECTION_STRING:
    raise EnvironmentError("Missing POSTGRES_CONNECTION_STRING in .env or environment.")

# === Nodes ===


async def classify_ticket(state: State) -> State:
    """This function classifies the support ticket based on its subject and description.

    It uses a language model to determine the category of the ticket, which can be one of:
    - Billing
    - Technical
    - Security
    - General

    The classification is stored in the 'category' field of the state.

    Args:
        state (State): The current state of the support ticket, which includes 'subject' and 'description'.

    Raises:
        ValueError: If the 'subject' or 'description' is missing or empty.
        ValueError: If the classification result is unexpected.

    Returns:
        State: The updated state with the classified category.
    """
    try:
        print("Invoking classifier LLM")
        llm = get_llm()

        if 'subject' not in state or 'description' not in state:
            raise ValueError("State must contain both 'subject' and 'description' keys.")
        if not state['subject'] or not state['description']:
            raise ValueError("Subject and description must not be empty.")

        structured_llm = llm.with_structured_output(Classification)
        prompt = PromptTemplate.from_template(CLASSIFICATION_PROMPT)
        prompt_value = prompt.invoke({
            'subject': str(state['subject']),
            'description': str(state['description'])
        })
        classification_output = structured_llm.invoke(prompt_value)
        if classification_output.output not in ['billing', 'technical', 'security', 'general']:
            raise ValueError(f"Unexpected classification result: {classification_output.output}")
        state['category'] = classification_output.output
    except Exception as e:
        print(f"Error during classification: {e}")
        state['category'] = 'general'

    print(f"Ticket classified as: {state['category']}")
    return state

async def rag_node(state: State) -> State:
    """This function retrieves relevant documents from the vector store based on the ticket's subject and description.

    It uses the PGVector vector store to find documents that match the category of the ticket.
    The retrieved documents are stored in the 'context_docs' field of the state.

    Note: This function assumes that the vector store has been properly initialized and contains relevant documents.

    Args:
        State (State): The current state of the support ticket, which includes 'subject', 'description', and 'category'.

    Raises:
        Exception: If there is an error during the retrieval process.

    Returns:
        State: 
    """
    try:
        print(f"Running RAG node for state: {state}")
        refresh_rag()  # Ensure the vector store is refreshed before retrieval all the embeddings are up to date

        if 'subject' not in state or 'description' not in state or 'category' not in state:
            raise ValueError("State must contain 'subject', 'description', and 'category' keys.")

        embedding_model = GoogleGenerativeAIEmbeddings(model="models/embedding-001")

        vectorstore = PGVector.from_existing_index(
            embedding=embedding_model,
            collection_name="support_docs",
            connection=POSTGRES_CONNECTION_STRING,
        )
        

        # Construct the query using subject, description, and retrive_improve keywords
        query = f"{state['subject']} {state['description']} {state.get('retrive_improve',[])}".strip()
        category = state['category'].lower()

        retriever = vectorstore.as_retriever(
            search_kwargs={"filter": {"category": category}, "k": 5}
        )

        docs = retriever.invoke(query)
        state['context_docs'] = docs
        return state
    except ValueError as ve:
        print(f"ValueError during RAG retrieval: {ve}")
        state['context_docs'] = [Document(page_content="No relevant documents found.")]
        return state
    except Exception as e:
        print(f"Error during RAG retrieval: {e}")
        state['context_docs'] = [Document(page_content="No relevant documents found.")]
        return state
    
rag_node_runnable = RunnableLambda(rag_node)

async def generate_draft(state: State) -> State:
    """This function generates a draft response for the support ticket based on the subject, description, and context documents.
    
    It uses a language model to create a professional and concise response, incorporating any review feedback if available.
    It updates the state with the generated draft response.

    Note: The function assumes that the 'context_docs' field in the state contains relevant documents for generating the response.
    
    Args:
        state (State): The current state of the support ticket, which includes 'subject', 'description', and 'context_docs'.

    Raises:
        Exception: If there is an error during the draft generation process.

    Returns:
        State:
    """
    try:
        print("Generating draft response")
        llm = get_llm()

        context_text = "\n\n".join([doc.page_content for doc in state['context_docs']])

        prompt = PromptTemplate.from_template(DRAFT_RESPONSE_PROMPT)
        

        prompt_value = prompt.invoke({
            "subject": state["subject"],
            "description": state["description"],
            "context": context_text,
            "review": state.get("feedback",[])
        })

        response = llm.invoke(prompt_value)

        if "draft" not in state or not isinstance(state["draft"], list):
            state["draft"] = []

        state["draft"].append(response.content.strip())
        print(f"Draft generated: {response.content.strip()}")
        return state
    except Exception as e:
        print(f"Error during draft generation: {e}")
        state["draft"] = ["An error occurred while generating the draft response."]
        return state
    
async def review_draft(state: State) -> State:
    """This function reviews the latest draft response for the support ticket.

    It uses a language model to evaluate the draft based on predefined criteria, such as professionalism, clarity, and adherence to company policy.
    The review results are stored in the state, including the status (approved or rejected), feedback, and any keywords for improvement.

    Args:
        state (State):

    Returns:
        State: 
    """
    try:
        print("Reviewing draft")
        llm = get_llm()

        latest_draft = state["draft"][-1] 
        print(f"Latest draft for review: {latest_draft}")

        prompt = PromptTemplate.from_template(REVIEW_DRAFT_PROMPT)
        prompt_value = prompt.invoke({"latest_draft": latest_draft, "subject": state["subject"], "description": state["description"]})
    
        structured_llm = llm.with_structured_output(ReviewResult)
        response = structured_llm.invoke(prompt_value)
        if response.feedback is None:
            raise ValueError("Feedback cannot be None. Please provide valid feedback.")
        
        print(f"Review result: {response.status}, Feedback: {response.feedback}, Keywords: {response.retrive_improve}")
        print("LLM Raw Response:", response)
        print("Type of response:", type(response))
        if response.status == "rejected" and response.feedback:
            state["feedback"].append(response.feedback)
            state["review_count"] = state.get("review_count", 0) + 1
            state['status'] = response.status
            state['retrive_improve'] = response.retrive_improve or []
            
        else:
            state["status"] = "approved"
            state["feedback"].append("Draft approved by reviewer.")
            state["review_count"] = state.get("review_count", 0) + 1
            state['retrive_improve'] = response.retrive_improve or []
    except Exception as e:
        print(f"Error during draft review: {e}")
        state["status"] = "rejected" 
        state["feedback"]= [f"An error occurred during the review process.{e}"]
        state["review_count"] = state.get("review_count", 0)  + 1
        state['retrive_improve'] = []
        
    return state
 
    
    
    
async def dump_state_to_csv(state: State) -> State:
    """this function dumps the state of a rejected ticket to a CSV file for record-keeping.

    It creates a directory named 'rejected_tickets' if it doesn't exist, and appends the ticket details to a CSV file.
    The CSV file includes the timestamp, subject, description, drafts, and feedbacks of the rejected ticket.

    Note: This function is called when the review count 2 .
    

    Args:
        state (State): 
    Returns:
        State: 
    """
    try:
        print("Dumping rejected ticket to CSV")
        os.makedirs("rejected_tickets", exist_ok=True)
        filepath = "rejected_tickets/rejected_tickets.csv"

        data = {
            "timestamp": datetime.datetime.now().isoformat(),
            "subject": state["subject"],
            "description": state["description"],
            "category": state["category"],
            "drafts": "\n---\n".join(state["draft"]),
            "feedbacks": "\n---\n".join(state["feedback"]),
        }

        df = pd.DataFrame([data])
        if os.path.exists(filepath):
            df.to_csv(filepath, mode="a", index=False, header=False, encoding="utf-8")
        else:
            df.to_csv(filepath, mode="w", index=False, header=True, encoding="utf-8")

        print(f"Rejected ticket saved to {filepath}")
        state["review_count"]=0
        return state
    except FileNotFoundError as fnf_error:
        print(f"File not found error during CSV dump: {fnf_error}")
        state["status"] = "error"
        state["feedback"].append("An error occurred while dumping the ticket to CSV.")
        return state
    except pd.errors.EmptyDataError as ede:
        print(f"Empty data error during CSV dump: {ede}")
        state["status"] = "error"
        state["feedback"].append("An error occurred while dumping the ticket to CSV.")
        return state
    except PermissionError as pe:
        print(f"Permission error during CSV dump: {pe}")
        state["status"] = "error"
        state["feedback"].append("An error occurred while dumping the ticket to CSV.")
        return state
    except Exception as e:
        print(f"Error during CSV dump: {e}")
        state["status"] = "error"
        state["feedback"].append("An error occurred while dumping the ticket to CSV.")
        return state


async def format_output(state: State) -> Output:
    """Formats the output based on the review status."""
    print("Formatting output")
    
    if state["status"] == "approved":
        return Output(message=state["draft"][-1])
        state.clear()
    else:
        return Output(message="A human will review your issue.")
        state.clear()


async def route_based_on_review(state: State) -> str:
    """Routes the state based on the review status.

    If the review status is "approved", it routes to format_output.
    If the review count is 2 or more, it routes to dump_state.
    Otherwise, it routes back to retriver for another attempt.

    """
    if state['status'] == "approved":
        return "format_output"
    elif state.get("review_count", 0) >= 2 :
        return "dump_state"
    else:
        return "retriver"



# === Build and compile the state graph ===

builder = StateGraph(State, input_schema=Input, output_schema=Output)

builder.add_node("classify_ticket", classify_ticket)
builder.add_node("retriver", rag_node_runnable)
builder.add_node("draft", generate_draft)
builder.add_node("review", review_draft)
builder.add_node("dump_state", dump_state_to_csv)
builder.add_node("format_output", format_output)

builder.add_edge(START, "classify_ticket")
builder.add_edge("classify_ticket", "retriver")
builder.add_edge("retriver", "draft")
builder.add_edge("draft", "review")
builder.add_conditional_edges("review", route_based_on_review)
builder.add_edge("dump_state", "format_output")

builder.set_finish_point("format_output")

graph = builder.compile()