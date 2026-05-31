import anthropic
import os
from sqlalchemy.orm import Session
from app.models.models import SentimentScore

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", "your-api-key"))

def analyze_sentiment(asset: str, headlines: list, db: Session):
    if not headlines:
        return
    
    text = "\n".join(headlines)
    prompt = f"Analyze the sentiment of the following news headlines for {asset}. Return a score between 0 and 100 and a short rationale.\n\n{text}\n\nFormat: Score: [number], Rationale: [text]"
    
    response = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=100,
        messages=[{"role": "user", "content": prompt}]
    )
    
    content = response.content[0].text
    # Basic parsing
    try:
        score_part = content.split("Score:")[1].split(",")[0].strip()
        rationale_part = content.split("Rationale:")[1].strip()
        score = float(score_part)
        
        sentiment = SentimentScore(
            asset=asset,
            score=score,
            rationale=rationale_part,
            source="Claude AI"
        )
        db.add(sentiment)
        db.commit()
        return sentiment
    except Exception as e:
        print(f"Error parsing Claude response: {e}")
        return None
