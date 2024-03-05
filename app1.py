import pandas as pd
from Bio import Entrez
import sqlite3
from openai import OpenAI
from dotenv import load_dotenv
import os
from itertools import combinations

# Load environment variables from .env file
load_dotenv()

# Set your email and API key for Entrez
Entrez.email = api_key = os.getenv('my_email')  # Replace with your email
Entrez.api_key = api_key = os.getenv('my_api_Key')  # Replace with your API key (optional)

def search_pubmed(query, mindate, maxdate):
    handle = Entrez.esearch(db='pubmed', sort='pub date', retmax='20', retmode='xml', term=query, mindate=mindate, maxdate=maxdate)
    results = Entrez.read(handle)
    handle.close()
    return results['IdList']

def fetch_details(id_list):
    if not id_list:
        return []
    ids = ','.join(id_list)
    handle = Entrez.efetch(db='pubmed', id=ids, retmode='xml')
    results = Entrez.read(handle, validate=False)
    handle.close()
    return results

def initialize_database(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gene TEXT,
            title TEXT,
            abstract TEXT,
            authors TEXT,
            journal TEXT,
            year TEXT,
            keywords TEXT,
            summary TEXT
        );
    """)
    conn.commit()
    conn.close()

def parse_article(article):
    article_data = article['MedlineCitation']['Article']
    
    # Extract the article title
    title = article_data.get('ArticleTitle', "")

    # Extract the abstract text
    abstract = article_data.get('Abstract', {}).get('AbstractText', [])
    abstract_text = ' '.join(abstract) if abstract else ''

    # Extract the authors list
    authors_list = article_data.get('AuthorList', [])
    authors = ', '.join([author['ForeName'] + ' ' + author['LastName'] for author in authors_list])

    # Extract the journal title
    journal = article_data.get('Journal', {}).get('Title', "")

    # Extract the publication year
    pub_date = article_data.get('Journal', {}).get('JournalIssue', {}).get('PubDate', {})
    year = pub_date.get('Year', "") if isinstance(pub_date, dict) else str(pub_date)

    # Extract keywords, if available
    keywords = article.get('KeywordList', [])
    keywords_text = ', '.join(keywords[0]) if keywords else ''  # Assuming the keywords are in the first list

    return title, abstract_text, authors, journal, year, keywords_text


def store_article(db_path, gene, title, abstract, authors, journal, year, keywords):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO articles (gene, title, abstract, authors, journal, year, keywords) VALUES (?, ?, ?, ?, ?, ?, ?)", 
                   (gene, title, abstract, authors, journal, year, keywords))
    conn.commit()
    conn.close()

def get_abstract_by_id(db_path, article_id):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    query = f"SELECT abstract FROM articles WHERE id = {article_id}"
    cursor.execute(query)
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def summarize_abstract(abstract):
    client = OpenAI(base_url="http://localhost:5001/v1", api_key="NULL")
    completion = client.chat.completions.create(
        model="marcoroni",  # Replace with your model name
        messages=[
            {"role": "system", "content": """You are a life science scientist. Your job is to create summaries with three components from an abstract with minimum words, follow these instructions: 1. Identify All Core Components: First, identify the main proteins, molecules, or complexes mentioned. These components are placed in the first and third place in the summary 2. Determine All Relationships: Establish how these core components are related linearly. Look for terms indicating relationships, such as 'upstream,' 'downstream,' 'activates,' 'inhibits,' 'recruit,' 'cause,' 'promote,' 'degrade,' 'depletion,' 'increase,' 'decrease' or 'interacts with.' Relationship placed in the second place in the summary. 3. Simplify All Relationships: Convert these relationships into a simplified, linear format: "Element one, relationship, element two." and write one summary per line. 4. Include Contextual Information: At the end, mention specific conditions or contexts (like cell type or genetic status) under which the pathway functions. Keep it as short as possible. Example example: 53BP1, inhibit, DNA end resection; 53BP1, recruit, RIF1; 53BP1 depletion, resistance to ,PARPi exposure; Context: DNA double strand break in G1"""},
            {"role": "user", "content": abstract}
        ],
        temperature=0.4,
    )
    return completion.choices[0].message.content if completion else ""

def store_summary(db_path, article_id, summary):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check if 'summary' column exists
    cursor.execute("PRAGMA table_info(articles)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'summary' not in columns:
        cursor.execute("ALTER TABLE articles ADD COLUMN summary TEXT")
    
    # Store the summary
    query = f"UPDATE articles SET summary = ? WHERE id = ?"
    cursor.execute(query, (summary, article_id))
    conn.commit()
    conn.close()


def process_genes(genes, mindate, maxdate, db_path):
    initialize_database(db_path)
    for gene in genes:
        id_list = search_pubmed(gene, mindate, maxdate)
        papers = fetch_details(id_list)
        for paper in papers['PubmedArticle']:
            title, abstract, authors, journal, year, keywords = parse_article(paper)
            store_article(db_path, gene, title, abstract, authors, journal, year, keywords)


# Previous functions definitions here (unchanged)

def generate_pairs(my_list):
    # Remove duplicates from the list by converting it to a set
    my_list = list(set(my_list))
    # Generate all 2-element pairs from the list
    pairs = list(combinations(my_list, 2))
    # Convert tuples to a formatted string
    formatted_pairs = [f'{pair[0]} AND {pair[1]}' for pair in pairs]
    return formatted_pairs

def main():
    genes = ['53BP1', 'RIF1', 'BRCA1']
    pairs_list = generate_pairs(genes)
    mindate = '2018/01/01'
    maxdate = '2023/12/01'
    db_path = 'publication.db'

    # Initialize the database
    initialize_database(db_path)

    # Process each gene pair
    for gene_pair in pairs_list:
        print(f"Processing {gene_pair}...")
        id_list = search_pubmed(gene_pair, mindate, maxdate)
        if id_list:
            papers = fetch_details(id_list)
            for paper in papers['PubmedArticle']:
                title, abstract, authors, journal, year, keywords = parse_article(paper)
                store_article(db_path, gene_pair, title, abstract, authors, journal, year, keywords)

    # Fetch and summarize abstracts
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id, abstract FROM articles")
    for article_id, abstract in cursor.fetchall():
        # Skip processing if the abstract is empty
        if not abstract.strip():
            continue

        summary = summarize_abstract(abstract)
        store_summary(db_path, article_id, summary)

    conn.close()

if __name__ == "__main__":
    main()
