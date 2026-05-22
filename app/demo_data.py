from datetime import datetime, timezone

from app.extractors.base import PaperMetadata
from app.models import Paper, PaperCitation, utcnow
from app.services.metadata import apply_metadata


DEMO_FIXTURES = {
    "2406.09246": PaperMetadata(
        source_type="arxiv",
        source_id="2406.09246",
        title="OpenVLA: An Open-Source Vision-Language-Action Model",
        authors=["Moo Jin Kim", "Karl Pertsch", "Siddharth Karamcheti"],
        abstract=(
            "OpenVLA is a generalist vision-language-action model for robotic control, "
            "trained on a mixture of robot datasets and designed for open research use."
        ),
        categories=["cs.RO", "cs.AI", "cs.LG"],
        primary_category="cs.RO",
        published_at=datetime(2024, 6, 13, tzinfo=timezone.utc),
        updated_at=datetime(2024, 6, 13, tzinfo=timezone.utc),
        canonical_url="https://arxiv.org/abs/2406.09246",
        pdf_url="https://arxiv.org/pdf/2406.09246.pdf",
    ),
    "2309.08600": PaperMetadata(
        source_type="arxiv",
        source_id="2309.08600",
        title="Towards Monosemanticity: Decomposing Language Models With Dictionary Learning",
        authors=["Trenton Bricken", "Adly Templeton", "Joshua Batson"],
        abstract=(
            "This work studies sparse autoencoders for decomposing neural network activations "
            "into more interpretable features."
        ),
        categories=["cs.LG", "cs.CL"],
        primary_category="cs.LG",
        published_at=datetime(2023, 9, 15, tzinfo=timezone.utc),
        updated_at=datetime(2023, 9, 15, tzinfo=timezone.utc),
        canonical_url="https://arxiv.org/abs/2309.08600",
        pdf_url="https://arxiv.org/pdf/2309.08600.pdf",
    ),
    "1706.03762": PaperMetadata(
        source_type="arxiv",
        source_id="1706.03762",
        title="Attention Is All You Need",
        authors=["Ashish Vaswani", "Noam Shazeer", "Niki Parmar"],
        abstract=(
            "The Transformer architecture replaces recurrence with attention mechanisms and "
            "became a foundation for modern sequence modeling."
        ),
        categories=["cs.CL", "cs.LG"],
        primary_category="cs.CL",
        published_at=datetime(2017, 6, 12, tzinfo=timezone.utc),
        updated_at=datetime(2017, 6, 12, tzinfo=timezone.utc),
        canonical_url="https://arxiv.org/abs/1706.03762",
        pdf_url="https://arxiv.org/pdf/1706.03762.pdf",
    ),
}

DEMO_BIBTEX = {
    "2406.09246": """@misc{kim2024openvlaopensourcevisionlanguageactionmodel,
      title={OpenVLA: An Open-Source Vision-Language-Action Model}, 
      author={Moo Jin Kim and Karl Pertsch and Siddharth Karamcheti},
      year={2024},
      eprint={2406.09246},
      archivePrefix={arXiv},
      primaryClass={cs.RO},
      url={https://arxiv.org/abs/2406.09246}, 
}
""",
    "2309.08600": """@misc{bricken2023monosemanticitydecomposinglanguagemodels,
      title={Towards Monosemanticity: Decomposing Language Models With Dictionary Learning}, 
      author={Trenton Bricken and Adly Templeton and Joshua Batson},
      year={2023},
      eprint={2309.08600},
      archivePrefix={arXiv},
      primaryClass={cs.LG},
      url={https://arxiv.org/abs/2309.08600}, 
}
""",
    "1706.03762": """@misc{vaswani2023attentionneed,
      title={Attention Is All You Need}, 
      author={Ashish Vaswani and Noam Shazeer and Niki Parmar and Jakob Uszkoreit and Llion Jones and Aidan N. Gomez and Lukasz Kaiser and Illia Polosukhin},
      year={2023},
      eprint={1706.03762},
      archivePrefix={arXiv},
      primaryClass={cs.CL},
      url={https://arxiv.org/abs/1706.03762}, 
}
""",
}


def apply_demo_fixtures(db) -> None:
    for paper in db.query(Paper).all():
        fixture = DEMO_FIXTURES.get(paper.source_id)
        if fixture:
            apply_metadata(paper, fixture)
        bibtex = DEMO_BIBTEX.get(paper.source_id)
        if bibtex:
            citation = db.get(PaperCitation, paper.id)
            if citation is None:
                db.add(
                    PaperCitation(
                        paper_id=paper.id,
                        bibtex=bibtex,
                        provider="arXiv API",
                        source_url=f"https://arxiv.org/bibtex/{paper.source_id}",
                    )
                )
            else:
                citation.bibtex = bibtex
                citation.provider = "arXiv API"
                citation.source_url = f"https://arxiv.org/bibtex/{paper.source_id}"
                citation.fetched_at = utcnow()
