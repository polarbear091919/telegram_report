"""Run the local workspace: python -m langgraph_tagger.workspace."""
import uvicorn

def main(view='reports'):
    print(f'Research Desk: http://127.0.0.1:8520/?view={view}', flush=True)
    uvicorn.run('langgraph_tagger.workspace.api:app', host='127.0.0.1', port=8520)
    return 0


if __name__ == '__main__':
    main()
