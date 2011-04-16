import redis

from django.utils import simplejson as json

from autocompleter import registry
from autocompleter import settings
from autocompleter import utils

class AutocompleterProvider(object):

    def __init__(self, obj):
        self.obj = obj

    def get_id(self):
        """
        The id for the object, should be unique for each model. Will normally not have to override this.
        """
        return str(self.obj.pk)
    
    def get_model_id(self):
        """
        Create a cross-model unique ID. Will normally not have to override this.
        """
        base_id = self.get_id()
        return "%s.%s" % (self.obj.__class__.__name__.lower(), base_id,)

    def get_term(self):
        """
        The term for the object, which will support autocompletion.
        """
        return str(self.obj)
    
    def get_terms(self):
        """
        Optional. Define this is an object can be searched for using more than one term.
        """
        return [self.get_term()]
    
    def get_norm_terms(self):
        """
        Normalize each term in list of terms. Will normally not have to override this.
        """
        return [utils.get_normalized_term(term) for term in self.get_terms()]

    def get_score(self):
        """
        The score for the object, that will dictate the order of autocompletion.
        """
        return 0

    def get_data(self):
        """
        The data you want to send along on a successful match.
        """
        return {}

    @classmethod
    def get_queryset(cls):
        """
        Get queryset representing all objects represented by this provider
        """
        return cls.model._default_manager.all()
    
class Autocompleter(object):
    """
    Autocompleter class
    """
    def __init__(self, name=settings.DEFAULT_NAME):
        self.name = name
        self.auto_name = 'autocompleter.%s' % (name,)
        self.exact_auto_name = 'autocompleter.%s.exact' % (name,)
        
        # Make connection with Redis
        self.redis = redis.Redis(host=settings.REDIS_CONNECTION['host'], 
            port=settings.REDIS_CONNECTION['port'], 
            db=settings.REDIS_CONNECTION['db'])

    def store(self, obj):
        """
        Add an object to the autocompleter
        """
        provider = self._get_provider(obj)
        if provider == None:
            return
        
        # Get some keys we need
        prefix_set_key = 'prefixes.%s' % (self.auto_name,)
        exact_term_set_key = 'norm_terms.%s' % (self.exact_auto_name,)

        # Get data from provider
        model_id = provider.get_model_id()
        terms = provider.get_terms()
        score = provider.get_score()
        data = provider.get_data()
        
        # Turn each normalized term into possible prefixes
        prefixes = []
        norm_terms = provider.get_norm_terms()
        for norm_term in norm_terms:
            prefixes = prefixes + utils.get_prefixes_for_term(norm_term)

        # Processes prefixes of object, placing object ID in sorted sets
        for prefix in prefixes:
            partial_prefix = ''
            for char in prefix:
                partial_prefix += char
                key = '%s.%s' % (self.auto_name, partial_prefix,)
                # Store prefix to model_id mapping, with score
                self.redis.zadd(key, model_id, score)
                # Store autocompleter to prefix mapping so we know all prefixes
                # of an autocompleter
                self.redis.sadd(prefix_set_key, partial_prefix)

        # Process normalized term of object, placing object ID in a sorted set 
        # representing exact matches
        for norm_term in norm_terms:
            key = '%s.%s' % (self.exact_auto_name, norm_term,)
            self.redis.zadd(key, model_id, score)
            # Store autocompleter to exact term mapping so we know all exact terms
            # of an autocompleter
            self.redis.sadd(exact_term_set_key, norm_term)

        # Store ID to data mapping
        self.redis.hset(self.auto_name, model_id, self._serialize_data(data))

    def store_all(self):
        """
        Store all objects of all providers register with this autocompleter.
        """
        provider_classes = registry.get_all(self.name)
        if provider_classes == None:
            return
        
        for provider_class in provider_classes:
            for obj in provider_class.get_queryset().iterator():
                self.store(obj)

    def remove(self, obj):
        """
        Remove an object from the autocompleter
        """
        provider = self._get_provider(obj)
        if provider == None:
            return
        
        # Get some keys we need
        prefix_set_key = 'prefixes.%s' % (self.auto_name,)
        exact_term_set_key = 'norm_terms.%s' % (self.exact_auto_name,)

        # Get data from provider
        model_id = provider.get_model_id()
        terms = provider.get_terms()
        
        # Turn each term into possible prefixes
        prefixes = []
        norm_terms = provider.get_norm_terms()
        for norm_term in norm_terms:
            prefixes = prefixes + utils.get_prefixes_for_term(norm_term)

        # Processes prefixes of object, removing object ID from sorted sets
        for prefix in prefixes:
            partial_prefix = ''
            for char in prefix:
                partial_prefix += char
                key = '%s.%s' % (self.auto_name, partial_prefix,)
                self.redis.zrem(key, model_id)
        
        # Process normalized term of object, placing object ID in a sorted set 
        # representing exact matches
        for norm_term in norm_terms:
            key = '%s.%s' % (self.exact_auto_name, norm_term,)
            self.redis.zrem(key, model_id,)

        # Remove model ID to data mapping
        self.redis.hdel(self.auto_name, model_id)

    def remove_all(self):
        """
        Remove all objects for a given autocompleter.
        This will clear the autocompleter even when the underlying objects don't exist.
        """
        # Get list of all prefixes for autocompleter
        prefix_set_key = 'prefixes.%s' % (self.auto_name,)
        prefixes = self.redis.smembers(prefix_set_key)
    
        # Get list of all exact match term for autocompleter
        exact_term_set_key = 'norm_terms.%s' % (self.exact_auto_name,)
        norm_terms = self.redis.smembers(exact_term_set_key)
    
        # For each prefix, delete sorted set
        for prefix in prefixes:
            key = '%s.%s' % (self.auto_name, prefix,)
            self.redis.zremrangebyrank(key, 0, -1)
            # Delete the original prefix entry
            self.redis.srem(prefix_set_key, prefix)

        # For each exact match term, deleting sorted set
        for norm_term in norm_terms:
            key = '%s.%s' % (self.exact_auto_name, norm_term,)
            self.redis.zremrangebyrank(key, 0, -1)
            # Delete the original exact match term entry
            self.redis.srem(exact_term_set_key, norm_term)

        # Remove all model ID to data mappings
        model_ids = self.redis.hkeys(self.auto_name)
        for model_id in model_ids:
            self.redis.hdel(self.auto_name, model_id)
        

    def suggest(self, term):
        """
        Suggest matching objects, given a term
        """
        norm_term = utils.get_normalized_term(term)
        auto_term = '%s.%s' % (self.auto_name, norm_term)
        ids = self.redis.zrange(auto_term, 0, settings.MAX_RESULTS - 1)
        if len(ids) == 0:
            return []

        # If we prioritize exact matches, we need to grab them and merge them with our
        # other matches
        if settings.MOVE_EXACT_MATCHES_TO_TOP:
            # Grab exact term match IDs
            exact_auto_term = '%s.%s' % (self.exact_auto_name, norm_term,)
            exact_ids = self.redis.zrange(exact_auto_term, 0, settings.MAX_RESULTS - 1)

            # Need to reverse exact IDs so high scores are behind low scores, since we 
            # are inserted in front of list.
            exact_ids.reverse()

            # Merge exact IDs with non-exact IDs, puttting exacts IDs in front and removing
            # from regular ID list if necessary
            for i in exact_ids:
                if i in ids:
                    ids.remove(i)
                ids.insert(0, i)
        
            if len(ids) > settings.MAX_RESULTS:
                ids = ids[:settings.MAX_RESULTS]

        # Get match data based on our ID list
        results = self.redis.hmget(self.auto_name, ids)
        # We shouldn't have any bogus matches, but if we do clear out before we deserialize
        results = [i for i in results if i != None]
        results = [self._deserialize_data(i) for i in results]
        return results
    
    def exact_suggest(self, term):
        """
        Suggext matching objects exacting matching term given, given a term
        """
        norm_term = utils.get_normalized_term(term)
        exact_auto_term = '%s.%s' % (self.exact_auto_name, norm_term,)
        exact_ids = self.redis.zrange(exact_auto_term, 0, settings.MAX_RESULTS - 1)
        if len(exact_ids) == 0:
            return []
        
        # Get match data based on our ID list
        results = self.redis.hmget(self.auto_name, exact_ids)
        # We shouldn't have any bogus matches, but if we do clear out before we deserialize
        results = [i for i in results if i != None]
        results = [self._deserialize_data(i) for i in results]
        return results
    
    def _get_provider(self, obj):
        try:
            provider_class = registry.get(self.name, type(obj))
            if provider_class == None:
                return None
            return provider_class(obj)
        except KeyError:
            raise TypeError("Don't know what do with %s" % obj.__class__.__name__)
    
    def _serialize_data(self, data_dict):
        return json.dumps(data_dict)

    def _deserialize_data(self, raw):
        return json.loads(raw)