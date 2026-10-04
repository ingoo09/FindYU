from uuid import uuid4

from langgraph.types import (
    Command,
)

from .models import ModelManager
from .metadata import MetadataRepository
from .vector_store import VectorStore
from .query_parser import QueryParser
from .ranker import Ranker
from .search_engine import SearchEngine
from .registration import RegistrationService
from .prompt_loader import PromptLoader
from .workflow import FindYUWorkflow


class FindYUApp:
    """
    FindYU의 최상위 객체.

    Frontend / FastAPI에서는 내부 객체들을 직접 다루지 않고
    이 객체의 메서드만 호출하면 된다.

    public methods:
    - initialize()
    - search()
    - resume_search()
    - register()
    """

    def __init__(
        self,
        config,
        paths,
    ):
        self.cfg = config
        self.paths = paths

        # Prompt 파일 loader
        self.prompt_loader = (
            PromptLoader(
                config.prompt_dir
            )
        )

        # Model / DB / Retrieval
        self.models = (
            ModelManager(
                config
            )
        )

        self.metadata = (
            MetadataRepository(
                paths.metadata_path,
                config,
            )
        )

        self.vector_store = (
            VectorStore(
                paths,
                self.models,
                config,
            )
        )

        # Query parser
        self.parser = (
            QueryParser(
                config,
                self.prompt_loader,
            )
        )

        # Ranking
        self.ranker = (
            Ranker(
                config
            )
        )

        # Search
        self.search_engine = (
            SearchEngine(
                config=config,
                parser=self.parser,
                vector_store=
                    self.vector_store,
                metadata=
                    self.metadata,
                ranker=
                    self.ranker,
            )
        )

        # Registration
        self.registration_service = (
            RegistrationService(
                config=config,
                paths=paths,
                metadata=
                    self.metadata,
                vector_store=
                    self.vector_store,
                prompt_loader=
                    self.prompt_loader,
            )
        )

        # LangGraph
        self.workflow = (
            FindYUWorkflow(
                self.search_engine,
                self.registration_service,
            )
        )

    @staticmethod
    def _thread_config(
        thread_id,
    ):
        return {
            "configurable": {
                "thread_id":
                    thread_id
            }
        }

    def initialize(self):
        """
        서버/프로그램 시작 시 한 번 실행.

        현재 DB 이미지로 FAISS index 생성.
        """
        self.vector_store.build()

    def search(
        self,
        query,
        image_path=None,
    ):
        thread_id = (
            str(uuid4())
        )

        result = (
            self.workflow
            .search_graph
            .invoke(
                {
                    "query":
                        query,

                    "image_path":
                        image_path,

                    "retry_count":
                        0,

                    "stop":
                        False,
                },

                config=
                    self._thread_config(
                        thread_id
                    ),
            )
        )

        return (
            thread_id,
            result,
        )

    def resume_search(
        self,
        thread_id,
        text=None,
        image_path=None,
        stop=False,
    ):
        return (
            self.workflow
            .search_graph
            .invoke(
                Command(
                    resume={
                        "text":
                            text,

                        "image_path":
                            image_path,

                        "stop":
                            stop,
                    }
                ),

                config=
                    self._thread_config(
                        thread_id
                    ),
            )
        )

    def register(
        self,
        image_path,
        location,
        found_time,
    ):
        return (
            self.workflow
            .registration_graph
            .invoke({
                "image_path":
                    image_path,

                "location":
                    location,

                "found_time":
                    found_time,
            })
        )
