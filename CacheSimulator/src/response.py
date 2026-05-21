class Response:
    """Container representing a cache response.

    Attributes:
        hit_list (Dict[str, bool]): Mapping of component/actor names to hit status.
        time (Union[int, float]): Cumulative time cost associated with the response.
        actor (str): Identifier of the actor producing the response.
        data (str): Optional payload or metadata.
    """

    def __init__(self, hit_list: Dict[str, bool], time: Union[int, float], actor: str = "UNKNOWN", data: str = "") -> None:
        """Initialize a Response instance.

        Args:
            hit_list: Mapping of names to boolean hit statuses.
            time: Initial cumulative time value.
            actor: Optional actor identifier (default "UNKNOWN").
            data: Optional data payload (default empty string).
        """
        self.hit_list = hit_list
        self.time = time
        self.actor = actor
        self.data = data

    def deepen(self, time: Union[int, float], name: str) -> None:
        """Mark a named entry as a miss and increase the cumulative time.

        The named entry in hit_list will be set to False and the provided time
        value will be added to the Response's cumulative time.

        Args:
            time: Time to add to the cumulative time.
            name: Key in hit_list to mark as False.
        """
        self.hit_list[name] = False
        self.time += time