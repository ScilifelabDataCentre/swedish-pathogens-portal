from utils.views import BaseTemplateView
import os


class Dashboards(BaseTemplateView):
    template_name = "dashboards/index.html"
    title = "Dashboards"
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['dashboards'] = [
            {
                'id': 'wastewater-sars-cov2',
                'title': 'Wastewater: SARS-CoV-2 Quantification',
                'description': 'Explore SARS-CoV-2 levels in wastewater across Sweden. Weekly data from SLU-SEEC tracks COVID-19 trends, covering 43% of the population, and aids in outbreak prediction.',
                'icon': 'water',
                'url': 'seec-wbs',
                'status': 'active',
                'last_updated': '2024-01-15',
                'topics': ['Wastewater Surveillance', 'COVID-19', 'Infectious Diseases', 'Epidemiology']
            },
            {
                'id': 'wastewater-influenza',
                'title': 'Wastewater: Influenza Quantification (SLU)',
                'description': 'Explore Influenza A and B virus levels in wastewater across Sweden. Weekly data from SLU-SEEC tracks Influenza trends, covering 43% of the Swedish population.',
                'icon': 'water',
                'url': None,
                'status': 'coming_soon',
                'last_updated': None,
                'topics': ['Wastewater Surveillance', 'Influenza', 'Epidemiology']
            },
            {
                'id': 'wastewater-rsv',
                'title': 'Wastewater: RSV Quantification (SLU)',
                'description': 'Explore Respiratory Syncytial Virus (RSV) levels in wastewater across Sweden. Weekly data from SLU-SEEC tracks RSV trends, covering a significant portion of the population.',
                'icon': 'water',
                'url': None,
                'status': 'coming_soon',
                'last_updated': None,
                'topics': ['Wastewater Surveillance', 'RSV', 'Epidemiology']
            },
            {
                'id': 'wastewater-enteric',
                'title': 'Wastewater: Enteric Virus Quantification (GU)',
                'description': 'Enteric virus levels in Gothenburg\'s wastewater, including norovirus and adenovirus. Data from the Norder group\'s weekly analysis at Ryaverket WWTP helps predict outbreaks.',
                'icon': 'water',
                'url': None,
                'status': 'coming_soon',
                'last_updated': None,
                'topics': ['Wastewater Surveillance', 'Enteric Viruses', 'Epidemiology']
            },
            {
                'id': 'vaccination-covid',
                'title': 'Vaccine Administration: COVID-19',
                'description': 'The Swedish Health Agency (Folkhälsomyndigheten) provide data and information related to COVID-19 in Sweden. Visualisations show multiple aspects of vaccination coverage across different counties.',
                'icon': 'shield',
                'url': None,
                'status': 'coming_soon',
                'last_updated': None,
                'topics': ['COVID-19', 'Infectious Diseases']
            },
            {
                'id': 'serology-scilifelab',
                'title': 'Serology Tests for SARS-CoV-2 at SciLifeLab',
                'description': 'The dashboard displays the SARS-CoV-2 serology tests completed over time at the SciLifeLab Autoimmunology and Serology Profiling unit. Shows total tests and positive/negative results over time.',
                'icon': 'dna',
                'url': None,
                'status': 'coming_soon',
                'last_updated': None,
                'topics': ['COVID-19', 'Infectious Diseases']
            }
        ]
        return context


class SEECWastewater(BaseTemplateView):
    template_name = "dashboards/seec-wbs.html"
    title = "Virus surveillance in wastewater from SLU-SEEC"


class SEECMethodology(BaseTemplateView):
    template_name = "dashboards/seec-methodology.html"
    title = "Wastewater: Methodology and sampling sites (SLU-SEEC)"


class SEECVirus(BaseTemplateView):
    template_name = "dashboards/seec-virus.html"

    # Map URL slug -> display name and direct permalink (paste yours here during prototyping)
    VIRUS_CONFIG = {
        "sars-cov-2": {
            "title": "Wastewater: SARS-CoV-2 (SLU-SEEC)",
            "url": "http://localhost:8088/superset/dashboard/p/GrzobZAob6m/",
        },
        "influenza-a": {
            "title": "Wastewater: Influenza A (SLU-SEEC)",
            "url": "http://localhost:8088/superset/dashboard/p/bVz4WAv3dy2/",
        },
        "influenza-b": {
            "title": "Wastewater: Influenza B (SLU-SEEC)",
            "url": "http://localhost:8088/superset/dashboard/p/9Mr3kZPo1yP/",
        },
        "rsv": {
            "title": "Wastewater: RSV (SLU-SEEC)",
            "url": "http://localhost:8088/superset/dashboard/p/AQeoaJe3yMl/",
        },
    }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        slug = self.kwargs.get("virus")
        cfg = self.VIRUS_CONFIG.get(slug)

        # Use direct URL from config (simpler for prototyping)
        permalink = cfg.get("url")

        # Ensure a native look: standalone=2 if not already present
        if "standalone=" not in permalink:
            sep = "&" if "?" in permalink else "?"
            permalink = f"{permalink}{sep}standalone=3"

        context["title"] = cfg["title"]
        context["iframe_src"] = permalink
        context["virus_slug"] = slug
        return context