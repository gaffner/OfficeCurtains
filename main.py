import uvicorn
from server import app

1   
def main():
    uvicorn.run(app, host='0.0.0.0', port=8000)


# Running the FastAPI app (you can use `uvicorn` to run this in your terminal)
if __name__ == '__main__':
    main()
