class Response:
    def __init__(self, hit_list, time, actor="UNKNOWN", data=""):
        """Initialize a Response instance.

        Parameters
            hit_list
                dict
                Mapping from actor name to boolean indicating hit status.
            time
                int or float
                Initial time/cost for the response.
            actor
                str, optional
                Identifier of the actor producing the response (default "UNKNOWN").
            data
                any, optional
                Optional payload attached to the response (default empty string).
        """
        self.hit_list = hit_list
        self.time = time
        self.actor = actor
        self.data = data

    def deepen(self, time, name):
        """Apply additional time cost and mark an actor as not hit.

        This method sets hit_list[name] to False and increments the response's
        total time by the provided amount.

        Parameters
            time
                int or float
                Amount of time to add to the response's total time.
            name
                str
                Actor name whose hit status will be changed to False.

        Returns
            None
        """
        self.hit_list[name] = False
        self.time += time

