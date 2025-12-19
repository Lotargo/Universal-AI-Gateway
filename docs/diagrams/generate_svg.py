
import os

class SVGGenerator:
    def __init__(self, width, height, bg_color="#2d2d2d"):
        self.width = width
        self.height = height
        self.elements = []
        self.bg_color = bg_color
        # Add background rect
        self.add_rect(0, 0, width, height, fill=bg_color, stroke="none")

    def add_rect(self, x, y, w, h, fill="#333", stroke="#bbf", stroke_width=2, text=None, text_color="#fff", corner_radius=5):
        rect = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{corner_radius}" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}" />'
        self.elements.append(rect)
        if text:
            # Simple centering
            font_size = 14
            # Break text into lines if needed (manual for now)
            lines = text.split('\n')
            line_height = 20
            start_y = y + (h / 2) + (font_size / 3) - ((len(lines) - 1) * line_height / 2)

            for i, line in enumerate(lines):
                cur_y = start_y + (i * line_height)
                txt = f'<text x="{x + w/2}" y="{cur_y}" font-family="Arial" font-size="{font_size}" fill="{text_color}" text-anchor="middle">{line}</text>'
                self.elements.append(txt)

    def add_group_box(self, x, y, w, h, label, fill="none", stroke="#666"):
        self.add_rect(x, y, w, h, fill=fill, stroke=stroke, stroke_width=1, corner_radius=0)
        # Label at top left
        if label:
            txt = f'<text x="{x + 10}" y="{y + 20}" font-family="Arial" font-size="12" fill="#aaa" text-anchor="start" font-weight="bold">{label}</text>'
            self.elements.append(txt)

    def add_arrow(self, x1, y1, x2, y2, color="#fff", width=2):
        # Line
        line = f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}" marker-end="url(#arrowhead)" />'
        self.elements.append(line)

    def save(self, filename):
        svg_content = f'''<svg width="{self.width}" height="{self.height}" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
      <polygon points="0 0, 10 3.5, 0 7" fill="#fff" />
    </marker>
  </defs>
  {''.join(self.elements)}
</svg>'''
        with open(filename, "w", encoding="utf-8") as f:
            f.write(svg_content)
        print(f"Generated {filename}")

def generate_current_architecture():
    # Size: 800x600
    svg = SVGGenerator(800, 600)

    # --- Main Application (Left) ---
    svg.add_group_box(50, 50, 300, 400, "Main Application")
    svg.add_rect(100, 100, 200, 50, text="User Request", fill="#444")
    svg.add_rect(100, 200, 200, 50, text="StreamingManager", fill="#444")
    svg.add_rect(100, 300, 200, 50, text="Retry Loop (x3)", fill="#f9f", stroke="#fff", text_color="#000") # Highlighted

    svg.add_arrow(200, 150, 200, 200) # User -> SM
    svg.add_arrow(200, 250, 200, 300) # SM -> Logic

    # --- Native Tools (Right) ---
    svg.add_group_box(450, 50, 300, 400, "Native Tools (Swarm)")
    svg.add_rect(500, 100, 200, 50, text="SmartSearchTool", fill="#444")
    svg.add_rect(470, 200, 120, 50, text="Worker 1", fill="#444")
    svg.add_rect(610, 200, 120, 50, text="Worker 2", fill="#444")
    svg.add_rect(500, 300, 200, 50, text="Internal Retry Loop\n(Duplicated)", fill="#f9f", stroke="#fff", text_color="#000") # Highlighted

    svg.add_arrow(200, 250, 500, 125) # SM -> Tool (Cross group)

    svg.add_arrow(550, 150, 530, 200) # Tool -> W1
    svg.add_arrow(650, 150, 670, 200) # Tool -> W2
    svg.add_arrow(530, 250, 550, 300) # W1 -> Logic
    svg.add_arrow(670, 250, 650, 300) # W2 -> Logic

    # --- Infrastructure (Bottom) ---
    svg.add_group_box(250, 480, 300, 100, "Infrastructure")
    svg.add_rect(280, 510, 240, 50, text="ApiKeyManager\n(Redis/Env)", fill="#222", stroke="#666")

    # Arrows to Infra
    svg.add_arrow(200, 350, 300, 510) # SM Logic -> KM
    svg.add_arrow(600, 350, 500, 510) # Tool Logic -> KM

    svg.save("docs/diagrams/current_architecture.svg")

def generate_target_architecture():
    svg = SVGGenerator(800, 600)

    # --- Consumers (Top) ---
    svg.add_group_box(50, 50, 700, 150, "Consumers")
    svg.add_rect(100, 100, 150, 50, text="StreamingManager", fill="#444")
    svg.add_rect(325, 100, 150, 50, text="SmartSearchTool", fill="#444")
    svg.add_rect(550, 100, 150, 50, text="Future Tool", fill="#444")

    # --- Unified Client Layer (Center) ---
    svg.add_group_box(200, 250, 400, 200, "Unified Client Layer")
    # High Contrast Core Service Node
    svg.add_rect(250, 300, 300, 50, text="CoreLLMService", fill="#333", stroke="#bbf", stroke_width=4, text_color="#fff")
    svg.add_rect(250, 370, 300, 50, text="Retry & Rotation Policy", fill="#444")

    svg.add_arrow(400, 350, 400, 370) # Service -> Policy

    # Arrows from Consumers to Service
    svg.add_arrow(175, 150, 300, 300)
    svg.add_arrow(400, 150, 400, 300)
    svg.add_arrow(625, 150, 500, 300)

    # --- Infrastructure (Bottom Right) ---
    svg.add_group_box(500, 480, 250, 100, "Infrastructure")
    svg.add_rect(525, 510, 200, 50, text="ApiKeyManager", fill="#222", stroke="#666")

    # --- Providers (Bottom Left) ---
    svg.add_rect(150, 510, 150, 50, text="Providers\n(HTTP)", fill="#222", stroke="#666")

    # Arrows from Policy
    svg.add_arrow(400, 420, 225, 510) # Policy -> Providers
    svg.add_arrow(400, 420, 625, 510) # Policy -> KM

    svg.save("docs/diagrams/target_architecture.svg")

if __name__ == "__main__":
    generate_current_architecture()
    generate_target_architecture()
