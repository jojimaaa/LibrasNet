PUPPETEER_EXECUTABLE_PATH=$(which chromium || which chromium-browser) pandoc documentacao.md -o documentacao.pdf --pdf-engine=xelatex --filter mermaid-filter -V lang=pt-BR -V geometry:margin=1in

rm mermaid-filter.err

echo "Generated documentacao.pdf"
