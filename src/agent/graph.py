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

    try:
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
    print(f"Running RAG node for state: {state}")
    refresh_rag()

    embedding_model = GoogleGenerativeAIEmbeddings(model="models/embedding-001")

    vectorstore = PGVector.from_existing_index(
        embedding=embedding_model,
        collection_name="support_docs",
        connection=POSTGRES_CONNECTION_STRING,
    )

    query = f"{state['subject']} {state['description']}".strip()
    category = state['category'].lower()

    retriever = vectorstore.as_retriever(
        search_kwargs={"filter": {"category": category}, "k": 5}
    )

    docs = retriever.invoke(query)
    state['context_docs'] = docs
    return state

rag_node_runnable = RunnableLambda(rag_node)

async def generate_draft(state: State) -> State:
    print("Generating draft response")
    llm = get_llm()

    context_text = "\n\n".join([doc.page_content for doc in state['context_docs']])

    prompt = PromptTemplate.from_template(DRAFT_RESPONSE_PROMPT)
    if "feedback" not in state or not isinstance(state["feedback"], list):
        state["feedback"] = []

    prompt_value = prompt.invoke({
        "subject": state["subject"],
        "description": state["description"],
        "context": context_text,
        "review": state["feedback"]
    })

    response = llm.invoke(prompt_value)

    if "draft" not in state or not isinstance(state["draft"], list):
        state["draft"] = []

    state["draft"].append(response.content.strip())
    print(f"Draft generated: {response.content.strip()}")
    return state

async def review_draft(state: State) -> State:
    print("Reviewing draft")
    llm = get_llm()

    latest_draft = state["draft"][-1]
    

    prompt = PromptTemplate.from_template(REVIEW_DRAFT_PROMPT)
    prompt_value = prompt.invoke({"latest_draft": latest_draft, "subject": state["subject"], "description": state["description"]})

    structured_llm = llm.with_structured_output(ReviewResult)
    response = structured_llm.invoke(prompt_value)

    print(f"Review result: {response.status}, Feedback: {response.feedback}, Keywords: {response.retrive_improve}")

    if response.status == "rejected" and response.feedback:
        state["feedback"].append(response.feedback)
        state["review_count"] = state.get("review_count", 0) + 1
        state['status'] = response.status
        state['retrive_improve'] = response.retrive_improve or []
        
    else:
        state["status"] = "approved"
        state["feedback"].append("Draft approved by reviewer.")
        state["review_count"] = 0

    return state

def dump_state_to_csv(state: State) -> State:
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
    return state

def route_based_on_review(state: State) -> str:
    if state['status'] == "approved":
        return "format_output"
    elif state.get("review_count", 0) >= 2:
        return "dump_state"
    else:
        return "retriver"

async def format_output(state: State) -> Output:
    if state["status"] == "approved":
        return Output(message=state["draft"][-1])
    else:
        return Output(message="A human will review your issue.")

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